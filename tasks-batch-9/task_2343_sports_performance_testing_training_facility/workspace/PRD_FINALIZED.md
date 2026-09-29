# Sports Performance Facility API — Product Requirements Document

## 1. Introduction

An athlete performance centre sits at an awkward intersection of three businesses that normally run on separate software. It is a testing laboratory, where a movement screen and a periodic performance battery have to be scored against published normative data and reported back to teenagers and their parents in language they trust. It is a training floor, where coach-to-athlete ratios, equipment station rotations and travel-training logistics decide whether a session can legally and safely run at all. And it is a small retail and contracting operation, selling session packages to families and slot-based contracts to schools and clubs, each with its own expiry, freeze and no-show economics. Today those three functions are reconciled by hand at the front desk, which is why credits go missing, why an under-credentialled intern occasionally ends up as the only adult on the floor, and why a return-to-sport athlete can be booked into a competition-phase session the week before a physician has signed anything.

This document specifies the Sports Performance Facility API, the single system of record for that reconciliation. The API owns the athlete from intake screening through periodized program design, group session scheduling and execution, testing cadence and progress reporting, return-to-sport progression under medical supervision, and the two funding instruments — membership packages and team contracts — that pay for it all. It also owns the credential file for the coaching staff, because in this domain a lapsed certification is not a paperwork problem: it is a staffing shortfall that must propagate, immediately and visibly, to every roster the affected coach was holding.

Two design commitments run through every section that follows. First, **time is explicit**. The server keeps a logical UTC clock that only ever moves forward, and every date-sensitive rule — package expiry, clearance validity, insurance validity, decay of a stale test result — is evaluated against that clock rather than against wall-clock time, so that a whole season of behaviour can be driven deterministically. Second, **safety decisions are separated from performance decisions**. The coach who administers a return-to-sport criterion test is structurally barred from judging it, and the medical authority that signs a release holds no scheduling or commercial power. Those separations are enforced in code, not in policy documents.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level behaviour that applies uniformly across the API: authentication, the response envelope, pagination, the logical clock, common resource properties, concurrency control, numeric precision, the order in which validations fire, and the cascade discipline that keeps parent and child records aligned.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. Six roles exist, and these exact spellings are the only accepted values: `PerformanceDirector`, `Coach`, `MedicalProvider`, `FrontDesk`, `Athlete`, and `Guardian`. A request whose `X-User-Role` header is missing, empty, or not one of those six strings is rejected with `ERR_UNAUTHENTICATED` before any other evaluation takes place. The single exception is the logical-clock advance operation described in §2.4, which is a test-driving facility and does not require a role header.

Authorization is the second gate. Each endpoint in §4 lists the roles permitted to invoke it; a caller whose role is absent from that list is rejected with `ERR_UNAUTHORIZED`. This check deliberately runs **before** any path identifier is resolved, so an unauthorized caller cannot use 404-versus-403 differences to probe which resources exist.

The meaning of `X-User-ID` depends on the role:

- When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting `StaffMember`. This is what makes the credential gate and the segregation-of-duties gate enforceable: the value is copied into `administered_by_staff_id` when a test session is opened, and it is compared against that stored value when a stage decision or a clearance signature is later attempted. If the supplied `X-User-ID` does not resolve to a `StaffMember`, the request fails with `ERR_STAFF_MEMBER_NOT_FOUND`.
- When `X-User-Role` is `Athlete`, `X-User-ID` is the `id` of the acting `Athlete`. Ownership checks compare the `athlete_id` reached by the request — directly, or through the parent chain of the addressed `TestSession`, `Enrollment`, `MembershipPackage`, `ReturnToSportPlan`, `ClearanceDocument` or `TrainingProgram` — against `X-User-ID`.
- When `X-User-Role` is `Guardian`, `X-User-ID` is **the minor athlete's own `id`**, not a separate guardian identifier, so the ownership comparison is exactly the same one used for the `Athlete` role. A `Guardian` call additionally requires that the target athlete's `age_years` is under 18 and that the athlete has a non-null `guardian_email` on file. A `Guardian` acting for an adult athlete, or for a minor with no guardian contact recorded, is therefore a scope violation rather than a plain authorization failure.
- When `X-User-Role` is `PerformanceDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record or log it but never compares it to any entity's `id`.
- When `X-User-Role` is `MedicalProvider`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. It is not matched against any entity's `id`; it is, however, compared against the `administered_by_staff_id` recorded on a stage test for the segregation-of-duties rule of §2.11, and the licence identifier a provider supplies when signing is persisted separately as `provider_license_id`.
- When `X-User-Role` is `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.

Ownership scoping for the two athlete-facing roles is enforced on exactly these operations: reading a single athlete, reading an athlete's progress report, creating an enrollment, cancelling an enrollment, reading a single test session, reading a single membership package, reading a single return-to-sport plan, and reading a single clearance document. A violation on any of them returns `ERR_ATHLETE_SCOPE_VIOLATION`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination and Collection Filters

Every collection endpoint is paginated by offset. The `limit` query parameter caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. The `offset` query parameter skips that many rows and defaults to 0. Unless a section states otherwise, collections are sorted by `created_at` in ascending order. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

Collections also accept domain filters, all of them optional and all of them combinable with `limit` and `offset`:

- Athletes may be filtered by `sport`, `membership_status`, `training_clearance`, and `team_contract_id`.
- Injury records may be filtered by `athlete_id` and `status`.
- Test sessions may be filtered by `athlete_id`, `battery_type`, `status`, `administered_by_staff_id`, and `rts_plan_id`.
- Training programs may be filtered by `athlete_id` and `status`; program blocks by `training_program_id`, `predecessor_block_id`, and `phase`.
- Group sessions may be filtered by `site_code`, `session_status`, `staffing_status`, `team_contract_id`, and by a time window whose bounds are `from_at` and `to_at`.
- Enrollments may be filtered by `athlete_id`, `group_session_id`, `membership_package_id`, and `status`.
- Staff members may be filtered by `credential_status`; certifications by `staff_member_id`, `status`, and `cert_code`.
- Membership packages may be filtered by `athlete_id` and `status`; team contracts by `organization_type` and `status`.
- Return-to-sport plans may be filtered by `athlete_id`, `injury_record_id`, `status`, and `active_stage_test_id`; clearance documents by `athlete_id`, `rts_plan_id`, `status`, and `document_type`.

These filter channels are the supported way to traverse a relationship in reverse — for example, to find every enrollment funded by a particular package, or every block belonging to a particular program.

### 2.4. The Logical Clock and the Expiry Sweep

The server does not read wall-clock time. It maintains a **logical UTC clock** whose value at startup is exactly `2026-08-01T00:00:00Z` and which never falls back to real time. `POST /_clock/set_current_utc` moves that clock, taking a single field `current_utc` holding an RFC 3339 UTC instant. The clock is monotonic: an instant earlier than the current logical clock is refused with `ERR_CLOCK_REWIND_FORBIDDEN`, while an instant exactly equal to the current value is accepted and processed as a no-op sweep. The response reports the new `current_utc` alongside `clearance_documents_expired_count` and `packages_expired_count`.

Every successful clock advance runs an expiry sweep in a **pinned order**, and that order is part of the contract:

1. First, every `ClearanceDocument` whose `status` is `SIGNED` and whose `expires_on` falls earlier than the new logical date moves to `EXPIRED`. From that moment such a document can no longer satisfy any clearance requirement, and attempts that depend on it fail with `ERR_CLEARANCE_EXPIRED`.
2. Second, every `MembershipPackage` whose `status` is `ACTIVE`, `FROZEN`, or `DEPLETED` and whose `effective_expires_on` falls earlier than the new logical date moves to `EXPIRED`. Packages are visited in ascending `created_at` order. On expiry the unspent remainder is forfeited: the value of `sessions_remaining` is added to `sessions_forfeited` and `sessions_remaining` is then set to zero, which preserves the credit-conservation identity described in §3.6.
3. Third — and this is deliberate — `Certification` rows are **not** touched. Advancing the clock never lapses a certification. Certification status is re-derived only by a credential review or a renewal, so persisted credential state may legitimately lag the logical clock until an operator runs a review.

Liability insurance behaves in the opposite way to certifications: `liability_insurance_expires_on` is never swept, but it *is* evaluated live against the logical clock every time a credential gate fires.

### 2.5. Common Resource Properties

Every resource in this system — athletes, injury records, test sessions, training programs, program blocks, group sessions, enrollments, staff members, certifications, membership packages, team contracts, return-to-sport plans and clearance documents — carries the same four system-managed properties:

- **`id`** (string): a server-minted UUID. It carries no type prefix and no domain-specific formatting.
- **`created_at`** (string): an ISO 8601 timestamp in UTC with three fractional digits, stamped from the logical clock at creation.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations the server performs on its own initiative as part of a cascade.
- **`version`** (integer): a monotonically increasing counter that advances by one on every mutation of the resource. No resource in this system omits `updated_at` or `version`.

Because `version` advances on server-initiated cascades as well as on client-initiated writes, a client that reads a group session, then enrolls an athlete into it, is holding a stale `version` — a point that matters directly for §2.6.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to prove that it is acting on a view of the parent record that is still current. Both use the same rejection code, `ERR_STALE_VERSION`, returned with HTTP 412.

**Assigning a coach to a group session.** A `POST /group-sessions/{group_session_id}/coaches` request must include `expected_group_session_version`, a non-optional field carrying the `version` of the `GroupSession` the client last observed. If that value does not equal the session's current `version`, the assignment is rejected with `ERR_STALE_VERSION` (412). The guard is necessary precisely because adding a second, different coach is legitimate product behaviour and therefore cannot be caught by any state precondition: once an earlier coach assignment, an enrollment, or a roster lock has advanced the session's `version`, the client's picture of `assigned_staff`, `required_coach_count` and `staffing_status` is obsolete, and it must re-read before deciding whether another coach is needed.

**Appending a block to a training program.** A `POST /training-programs/{training_program_id}/blocks` request must include `expected_training_program_version`, a non-optional field carrying the `version` of the `TrainingProgram` the client last observed. A mismatch with the program's current `version` is rejected with `ERR_STALE_VERSION` (412). Appending further blocks to a `DRAFT` program is legitimate, but each new block's `start_week` must equal its predecessor's `end_week` plus one; a stale view of the chain would silently open a gap or an overlap in the periodization plan.

No other endpoint accepts a version field. Requests to endpoints outside these two must not be expected to carry one, and supplying one elsewhere has no concurrency effect.

### 2.7. Numeric Precision and Rounding Discipline

All rounding in this system is **round half up** — a value exactly on the midpoint rounds away from zero, never to even. The scale differs by quantity and is fixed:

- Risk scores, readiness figures and planned training load are carried to **2 decimal places**: `risk_score`, `injury_risk_score`, `readiness_index`, and `planned_load_units`.
- Percentiles are carried to **1 decimal place**: each entry's `percentile` inside `metric_percentiles`, the `composite_percentile` of a test session, `last_composite_percentile` on the athlete, and the derived `delta_percentile_points` and `attendance_rate_pct` of a progress report.
- Weighted athlete load, `athlete_units`, is carried to **1 decimal place**.
- All money is carried in **integer cents** with no fractional part: `charge_cents`, `no_show_fee_cents`, `price_cents`, `base_rate_cents`, `billed_rate_cents`, `billed_amount_cents`, and the reported `no_show_fee_total_cents`.
- Coach counts, station indices and week counts are integers, and where a formula divides to obtain them the result is rounded **up** to the next whole number.

Three places in this specification pin an **order of rounding** rather than merely a scale, because rounding early and rounding late produce different answers: the per-metric percentiles of a performance battery, the per-block contributions to a program's planned load, and the per-line no-show fees that a progress report totals. Each is spelled out where it is used, in §3.2, §3.3 and §3.8 respectively.

### 2.8. The Validation Ladder

Validation is a **single global ladder**, total and strictly ordered. When one request violates two rules, the rule that appears earlier in the ladder produces the response and the later violation is never reported. Implementations must not reorder these tiers for convenience, because the observable error identifier depends on the order.

1. **Authentication.** A missing or unrecognised `X-User-Role` → `ERR_UNAUTHENTICATED`. Applies to every endpoint except the logical-clock advance.
2. **Authorization.** The caller's role is not among the endpoint's permitted roles → `ERR_UNAUTHORIZED`. Evaluated before any path identifier is resolved.
3. **Path existence.** Every `{...}` path identifier must resolve to a live row of its entity, and the entity-specific not-found code is returned (see §2.9).
4. **Body foreign keys.** Every foreign-key value supplied in a request body must resolve to an existing row of the referenced entity, evaluated in the order the fields are declared for that operation, and the referenced entity's own not-found code is returned. This tier guards the creation of injury records, test sessions, training programs, program blocks, group sessions, coach assignments, enrollments, certifications, membership packages, contract-athlete links, return-to-sport plans, and clearance documents.
5. **Schema, enum and range.** Required fields must be present and every value must satisfy its declared type, enum domain, numeric range and any intra-body ordering rule → `ERR_INVALID_REQUEST`. The clock-advance monotonicity rule also sits at this tier, returning `ERR_CLOCK_REWIND_FORBIDDEN`.
6. **Ownership scope.** The `Athlete` and `Guardian` scoping rules of §2.1 → `ERR_ATHLETE_SCOPE_VIOLATION`.
7. **Optimistic concurrency.** The two version checks of §2.6 → `ERR_STALE_VERSION`. Placing this tier after schema validation but before every state and business check is intentional: a caller working from a stale read should be told to re-read, not handed a business error computed from state it has never seen.
8. **State.** The addressed entity must be in a state from which the requested transition is declared. A request against a terminal state returns `ERR_ALREADY_TERMINAL`; any other undeclared source state returns `ERR_INVALID_STATE`. Athlete suspension (`ERR_ATHLETE_SUSPENDED`) and duplicate enrollment (`ERR_DUPLICATE_ENROLLMENT`) are decided at this tier too.
9. **Segregation of duties.** The stage-decision and clearance-signature separations of §2.11 → `ERR_SEGREGATION_OF_DUTIES`.
10. **Athlete safety.** Screening, medical hold, stage clearance and clearance expiry → `ERR_MOVEMENT_SCREEN_REQUIRED`, `ERR_ATHLETE_MEDICAL_HOLD`, `ERR_STAGE_CLEARANCE_MISSING`, `ERR_CLEARANCE_EXPIRED`.
11. **Staff safety.** Credential and continuing-education gates → `ERR_STAFF_CREDENTIAL_LAPSED`, `ERR_CEU_REQUIREMENT_NOT_MET`.
12. **Business constraints.** Capacity, coaching ratio, readiness threshold, restricted-phase eligibility, and program block chaining → `ERR_SESSION_FULL`, `ERR_COACH_RATIO_EXCEEDED`, `ERR_READINESS_BELOW_THRESHOLD`, `ERR_RESTRICTED_PHASE_NOT_PERMITTED`, `ERR_PROGRAM_BLOCK_SEQUENCE_INVALID`.
13. **Temporal constraints.** Staff and athlete schedule overlaps, travel buffers, facility concurrency, and the enrollment window → `ERR_STAFF_SCHEDULE_CONFLICT`, `ERR_TRAVEL_BUFFER_VIOLATION`, `ERR_ATHLETE_SCHEDULE_CONFLICT`, `ERR_SITE_CONCURRENCY_EXCEEDED`, `ERR_ENROLLMENT_WINDOW_CLOSED`.
14. **Referential business rules.** Normative band availability, empty test sessions, contract activity, plan eligibility, and the void guard → `ERR_NORM_BAND_UNAVAILABLE`, `ERR_NO_TEST_RESULTS`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_INVALID_STATE`, `ERR_VOID_BLOCKED_BY_NO_SHOW`.
15. **Fiscal rules.** Funding availability and allowances → `ERR_NO_SESSION_CREDIT`, `ERR_PACKAGE_EXPIRED`, `ERR_OFFSITE_ALLOWANCE_EXHAUSTED`.

Within a tier, the individual orderings that matter are stated alongside the workflow they guard — notably the capacity-before-ratio rule of §3.7, the credential-before-scheduling rule of §3.5, and the clearance-before-staffing rule of §3.9.

### 2.9. Path Resolution and Not-Found Semantics

Path identifiers are resolved strictly left to right, and the first identifier that fails to resolve determines the response; the server does not continue on to look up later segments. Each identifier has its own dedicated code: `athlete_id` yields `ERR_ATHLETE_NOT_FOUND`, `injury_record_id` yields `ERR_INJURY_RECORD_NOT_FOUND`, `test_session_id` yields `ERR_TEST_SESSION_NOT_FOUND`, `training_program_id` yields `ERR_TRAINING_PROGRAM_NOT_FOUND`, `program_block_id` yields `ERR_PROGRAM_BLOCK_NOT_FOUND`, `group_session_id` yields `ERR_GROUP_SESSION_NOT_FOUND`, `enrollment_id` yields `ERR_ENROLLMENT_NOT_FOUND`, `staff_member_id` yields `ERR_STAFF_MEMBER_NOT_FOUND`, `certification_id` yields `ERR_CERTIFICATION_NOT_FOUND`, `membership_package_id` yields `ERR_MEMBERSHIP_PACKAGE_NOT_FOUND`, `team_contract_id` yields `ERR_TEAM_CONTRACT_NOT_FOUND`, `rts_plan_id` yields `ERR_RTS_PLAN_NOT_FOUND`, and `clearance_document_id` yields `ERR_CLEARANCE_DOCUMENT_NOT_FOUND`.

The same code set applies to foreign keys carried in a request body: a body referencing an absent program block, whether through `predecessor_block_id` or otherwise, returns `ERR_PROGRAM_BLOCK_NOT_FOUND`. When an acting `Coach` supplies an `X-User-ID` that does not correspond to a staff member, the response is `ERR_STAFF_MEMBER_NOT_FOUND`.

### 2.10. Cascade Integrity

Many operations in this facility touch more than one record, and the secondary effects are as much part of the contract as the primary one. Three cascade families recur, and each is fully specified where it is triggered:

**Refund cascades.** Whenever a held enrollment is released ahead of its session — because the athlete was suspended, placed on medical hold, had a clearance revoked, or because the session itself was cancelled — the funding that was set aside for it is returned to its source. A package-funded slot decrements `sessions_reserved` and increments `sessions_remaining`, and a package sitting in `DEPLETED` returns to `ACTIVE` once it again holds at least one credit. A contract-funded slot decrements `sessions_reserved` and increments `sessions_available`, and when the freed session was `OFFSITE` the contract's `offsite_sessions_used` is decremented as well.

**Waitlist cascades.** Every freed roster slot on a session that is still `SCHEDULED` or `ROSTER_LOCKED` immediately triggers waitlist promotion, described in full in §3.7. Promotion is a server-initiated mutation: it advances the promoted enrollment's `version` and the session's `version` without any client request against those rows.

**Credential cascades.** A credential review that lapses a certification does not stop at the certification row. It propagates to the owning staff member, then to every future group session that staff member was assigned to, then to the staffing state of those sessions, and finally to the station assignments of the enrollments on them. The full chain is set out in §3.4.

In all three families the server mutates records on its own initiative. Each such mutation refreshes the affected record's `updated_at` and increments its `version`, exactly as a client-initiated write would.

### 2.11. Segregation of Duties in Medical Clearance

The facility's medical governance rests on a single structural rule: **the person who measures is not the person who clears.** Two checks implement it, and both return `ERR_SEGREGATION_OF_DUTIES`.

When a stage decision is recorded on a return-to-sport plan, the acting `X-User-ID` must differ from the `administered_by_staff_id` stored on the plan's active stage test. The coach who ran the criterion test cannot be the identity that passes or fails the athlete on it.

When a clearance document is signed, the signing `X-User-ID` must likewise differ from the `administered_by_staff_id` of the test session referenced by the plan's active stage. In addition, a `MedicalProvider` who has already revoked a document earlier in the same plan may not sign a document for that plan.

Beyond these two checks, the role model itself enforces separation: a `PerformanceDirector` may not administer tests and may not make medical decisions; a `MedicalProvider` may not administer performance tests, schedule sessions, or transact commercially; a `Coach` may not activate programs, review credentials, or sign clearances; and a `FrontDesk` operator holds no clinical, credentialing or floor-execution authority at all.

## 3. Business Logic & Workflows

### 3.1. Athlete Intake and the Movement Screen

Registration is a front-desk act. A `FrontDesk` operator or the `PerformanceDirector` records the athlete's `full_name` (between 1 and 120 characters), their `date_of_birth` as a `YYYY-MM-DD` string that must fall strictly before the current logical date, the primary `sport` — one of `BASKETBALL`, `SOCCER`, `BASEBALL`, `VOLLEYBALL` or `TRACK` — and a `position` label of 1 to 40 characters written in upper snake case, such as `GUARD` or `MIDFIELDER`. Two optional fields complete the intake form. `guardian_email` holds the parent or guardian contact and defaults to null, but it is **required** whenever the athlete's derived `age_years` is under 18 at the moment of registration; omitting it for a minor is rejected as an invalid request. `maturity_offset_months` records the athlete's biological-versus-chronological maturity offset in whole months, accepted anywhere from negative 36 through positive 36 and defaulting to 0.

`age_years` is never supplied by a client. It is the number of days between `date_of_birth` and the current logical date, divided by 365.25, with any fraction discarded — that is, rounded down to a whole year. Because it is derived against the clock rather than stored, an athlete's age band can change purely as a consequence of a clock advance.

A new athlete arrives in two parallel states that evolve independently and gate participation separately. `membership_status` begins at `PENDING_INTAKE` and can later become `ACTIVE` or `SUSPENDED`. `training_clearance` begins at `SCREEN_PENDING` and can later become `CLEARED`, `RESTRICTED`, or `MEDICAL_HOLD`. Neither dimension is terminal. Alongside them sit counters that all start empty: `screen_count` and `attended_count` and `no_show_count` and `no_show_strikes` at 0, and `injury_risk_score`, `last_composite_percentile`, `last_performance_test_at`, `next_test_due_on` and `team_contract_id` all null. `readiness_index` is initialised from the readiness formula of §3.2, which with no test on file produces the default base.

While `training_clearance` is `SCREEN_PENDING` the athlete is inert: they cannot be enrolled in any group session, and no `PERFORMANCE_BATTERY` test session may be opened for them. Both attempts are refused with `ERR_MOVEMENT_SCREEN_REQUIRED`. The way out is the intake movement screen.

**Opening and populating a screen.** Only a `Coach` may open a test session, supplying the target `athlete_id` and the `battery_type`, which is either `MOVEMENT_SCREEN` or `PERFORMANCE_BATTERY` and is immutable once the session exists. The server copies the acting coach's `X-User-ID` into `administered_by_staff_id`, which is why an opener whose `credential_status` is `LAPSED`, or whose `liability_insurance_expires_on` precedes the current logical date, is refused with `ERR_STAFF_CREDENTIAL_LAPSED`. A `SUSPENDED` athlete may not have a test session opened for them at all, and that refusal — `ERR_ATHLETE_SUSPENDED` — is reported before any funding, ratio, safety or temporal evaluation, exactly as it is for a new enrollment, a program activation or a package purchase. A new session is `DRAFT`, with `results` empty, `result_count` at 0, `rts_plan_id` null, and `age_years_at_test`, `effective_age_years`, `metric_percentiles`, `composite_percentile`, `risk_score`, `asymmetry_points`, `variant_applied` and `finalized_at` all null.

Measurements are appended while the session is `DRAFT`, and only then; appending to a session that has already been finalized returns `ERR_ALREADY_TERMINAL`. The submission carries a `results` array whose rows each hold a `metric_code`, a numeric `value`, and a `side` marker, and the submitted rows replace whatever `results` held before, with `result_count` updated to match. A `MOVEMENT_SCREEN` append must carry exactly the five screen codes — `OH_SQUAT`, `HURDLE_STEP`, `INLINE_LUNGE`, `SL_HOP_L` and `SL_HOP_R` — with no duplicates and no other code, each scored as an integer from 0 through 3. Anything else is an invalid request.

**Scoring the screen.** Finalizing a `MOVEMENT_SCREEN` stamps `finalized_at` from the logical clock, moves `status` from `DRAFT` to `FINALIZED`, and computes the athlete's injury risk. A session with `result_count` of zero cannot be finalized at all and returns `ERR_NO_TEST_RESULTS`.

The screen's raw total is the sum of the five metric values, so it lies between 0 and 15. Separately, `asymmetry_points` is the absolute difference between the `SL_HOP_L` value and the `SL_HOP_R` value, and therefore lies between 0 and 3. A **deficit** is then formed by subtracting the raw total from the maximum attainable screen score of 15 and adding twice the asymmetry points — the asymmetry weight is 2.0, so a single point of left-right imbalance costs as much as two points of lost movement quality. That deficit is multiplied by a **history multiplier**, floored at zero, capped at a risk ceiling of 30.00, and rounded half up to two decimal places to produce `risk_score`. The same figure is written to the athlete's `injury_risk_score`, and `screen_count` increases by one.

The history multiplier is where the screen splits into two variants, and `variant_applied` records which one ran:

- **Intake screen** (`INTAKE_SCREEN`), when the athlete's `screen_count` is still 0 at finalize time: the history multiplier is forced to exactly 1.00. The intake screen scores movement quality only, because injury history is captured separately during intake and is deliberately not yet weighted.
- **Reassessment screen** (`REASSESSMENT_SCREEN`), when `screen_count` is 1 or more at finalize time: the history multiplier is the smaller of the injury-history cap of 1.45 and the quantity one plus 0.15 for each of the athlete's injury records whose `status` is `ACTIVE_REHAB` at finalize time. Identical movement scores therefore yield a strictly higher `risk_score` on reassessment once open rehabilitation exists, and can cross the restriction threshold that the same numbers cleared at intake.

The restriction threshold is 12.00 and it is **inclusive on the restricted side**. A `risk_score` of 12.00 or higher sets `training_clearance` to `RESTRICTED`; anything below 12.00 sets it to `CLEARED`. On the very first finalized screen, `membership_status` also moves from `PENDING_INTAKE` to `ACTIVE` — this transition requires the session to have been `DRAFT` at the moment of finalize, to belong to this athlete, and the athlete to still be `PENDING_INTAKE`. Finally `readiness_index` is recomputed. A reassessment screen re-runs the same clearance decision: a reassessment scoring 12.00 or above moves `CLEARED → RESTRICTED`, and a reassessment scoring below 12.00 moves `RESTRICTED → CLEARED` **only if** the athlete has no return-to-sport plan sitting in `STAGE_ACTIVE`, `STAGE_TESTING` or `MEDICAL_REVIEW`.

**Administrative suspension and reinstatement.** The `PerformanceDirector` may suspend an `ACTIVE` athlete directly, supplying a free-text `reason`. `membership_status` moves `ACTIVE → SUSPENDED` and the forward book is cleared: every enrollment of that athlete sitting in `RESERVED` or `WAITLISTED` on a group session whose `start_at` is later than the current logical clock and whose `session_status` is `SCHEDULED` or `ROSTER_LOCKED` becomes `CANCELED` with `cancel_reason` set to `ATHLETE_SUSPENDED`, each cancellation refunds its funding source exactly as described in §2.10, each freed slot triggers waitlist promotion on its session, and each affected session recomputes its coaching requirement. This is byte-for-byte the same chain the third no-show strike fires automatically, described in §3.8. Reinstatement is the mirror: `membership_status` moves `SUSPENDED → ACTIVE`, `no_show_strikes` is reset to 0 so the next no-show is charged at the base multiplier again, and `readiness_index` is recomputed. Crucially, `no_show_count` is **not** reset — it keeps feeding the attendance term of the readiness formula and the lifetime fee statement.

**Medical hold.** Only a `MedicalProvider` may place an athlete on hold, supplying a `hold_reason`. The transition is permitted from either `CLEARED` or `RESTRICTED` — both source states behave identically — and drives `training_clearance` to `MEDICAL_HOLD`. Its cascade is the forward-book clearance again: every `RESERVED` or `WAITLISTED` enrollment on a future `SCHEDULED` or `ROSTER_LOCKED` session becomes `CANCELED` with `cancel_reason` of `ATHLETE_SUSPENDED`, its funding refunded and its freed slot offered to the waitlist. While an athlete is on `MEDICAL_HOLD` no enrollment can be created for them regardless of funding, ratio or readiness, and the attempt returns `ERR_ATHLETE_MEDICAL_HOLD`. Only a signed `MEDICAL_HOLD_RELEASE` clearance document lifts the hold, as described in §3.9.

### 3.2. Injury History, Performance Testing and Progress Reporting

**Injury records.** A `MedicalProvider` or the `PerformanceDirector` records an injury, whether historical or fresh, against an `athlete_id`. The record names a `body_region` from `KNEE`, `SHOULDER`, `ANKLE`, `HIP`, `LUMBAR` or `ELBOW`; a `severity` of `MILD`, `MODERATE` or `SEVERE`; an `occurred_on` date in `YYYY-MM-DD` form that may not be later than the current logical date; and a boolean `rts_required` that defaults to false and, when true, makes the record eligible to anchor a return-to-sport progression. Every new record starts with `status` of `ACTIVE_REHAB`, and while it stays there it contributes to the reassessment history multiplier of §3.1 and to the return-to-sport weighting of §3.5. A `MedicalProvider` marks rehabilitation complete, moving `status` to `RESOLVED` and triggering a readiness recomputation; from then on the record no longer inflates either figure.

**The performance battery.** Once an athlete is out of `SCREEN_PENDING`, a `Coach` may open a `PERFORMANCE_BATTERY` session and append rows drawn from exactly three codes — `CMJ_CM` (countermovement jump height in centimetres), `SPRINT_10M_S` (ten-metre sprint time in seconds) and `IMTP_N` (isometric mid-thigh pull force in newtons). Any non-empty subset of the three is acceptable; duplicates and codes outside the three are invalid requests.

Finalizing a battery computes the athlete's standing against published norms. `age_years_at_test` is fixed at finalize time as the number of days between `date_of_birth` and the finalize date divided by 365.25, rounded down to a whole year. The **maturity variant** then chooses the age used for the normative lookup, and `variant_applied` records which one ran:

- **Raw norm** (`RAW_NORM`), when the absolute value of `maturity_offset_months` is under 12 months: the lookup age is `age_years_at_test`, and `effective_age_years` equals `age_years_at_test`.
- **Maturity adjusted** (`MATURITY_ADJUSTED`), when the absolute value of `maturity_offset_months` is 12 months or more — a full year or beyond of early or late maturation: the lookup age is `age_years_at_test` plus the maturity offset converted from months to whole years by dividing by 12 and rounding half up to a whole number, and `effective_age_years` records that adjusted age. Identical raw measurements are therefore scored against a different age band and yield a different `composite_percentile`.

The normative table is keyed on sport, position, an inclusive age band, and metric. A band row matches when its sport equals the athlete's `sport`, its position equals the athlete's `position`, and the lookup age falls at or above the band minimum and at or below the band maximum:

| Sport        | Position     | Age band | Metric         | p50    | p90    | Direction     |
| ------------ | ------------ | -------- | -------------- | ------ | ------ | ------------- |
| `BASKETBALL` | `GUARD`      | 13–14    | `CMJ_CM`       | 34.0   | 42.0   | higher better |
| `BASKETBALL` | `GUARD`      | 13–14    | `SPRINT_10M_S` | 1.85   | 1.69   | lower better  |
| `BASKETBALL` | `GUARD`      | 13–14    | `IMTP_N`       | 1400   | 1900   | higher better |
| `BASKETBALL` | `GUARD`      | 15–16    | `CMJ_CM`       | 40.0   | 50.0   | higher better |
| `BASKETBALL` | `GUARD`      | 15–16    | `SPRINT_10M_S` | 1.78   | 1.62   | lower better  |
| `BASKETBALL` | `GUARD`      | 15–16    | `IMTP_N`       | 1700   | 2300   | higher better |
| `BASKETBALL` | `GUARD`      | 17–18    | `CMJ_CM`       | 45.0   | 56.0   | higher better |
| `BASKETBALL` | `GUARD`      | 17–18    | `SPRINT_10M_S` | 1.72   | 1.56   | lower better  |
| `BASKETBALL` | `GUARD`      | 17–18    | `IMTP_N`       | 2000   | 2650   | higher better |
| `SOCCER`     | `MIDFIELDER` | 15–16    | `CMJ_CM`       | 36.0   | 45.0   | higher better |
| `SOCCER`     | `MIDFIELDER` | 15–16    | `SPRINT_10M_S` | 1.80   | 1.64   | lower better  |
| `SOCCER`     | `MIDFIELDER` | 15–16    | `IMTP_N`       | 1600   | 2150   | higher better |

Any combination of sport, position, age and metric outside this table has no band at all.

Each result row whose `metric_code` finds a matching band row is converted into a percentile by piecewise-linear interpolation anchored at the fiftieth and ninetieth percentiles. The fiftieth-percentile anchor is 50 and the span from the fiftieth to the ninetieth anchor is 40 points. For a **higher-is-better** metric, the raw percentile is 50 plus 40 multiplied by the quantity (the measured value minus p50) divided by (p90 minus p50). For a **lower-is-better** metric — where a faster sprint is a better sprint — the raw percentile is 50 plus 40 multiplied by the quantity (p50 minus the measured value) divided by (p50 minus p90). The raw percentile is then confined to the closed range from 1.0 to 99.0 and rounded half up to one decimal place. Each surviving metric contributes an entry to `metric_percentiles` holding its `metric_code`, its `percentile`, and a `norm_band_matched` marker identifying the band that scored it.

The composite is a weighted average with the weights renormalised over the metrics that actually matched: `CMJ_CM` carries weight 0.40, `SPRINT_10M_S` carries 0.35, and `IMTP_N` carries 0.25. Metrics with no matching band are excluded entirely rather than scored as zero, so the divisor is the sum of the weights of the matched metrics only. **The rounding order is pinned:** each metric's percentile is rounded to one decimal place *before* it enters the weighted sum, and the weighted average is then rounded half up to one decimal place exactly once, producing `composite_percentile`. Rounding once at the end instead is not the contract. `composite_percentile` is null for a `MOVEMENT_SCREEN`, just as `risk_score` and `asymmetry_points` are null for a `PERFORMANCE_BATTERY`.

If a battery holds result rows but not one of them resolves to a band for the athlete's sport, position and lookup age, no percentile can be computed and finalize fails with `ERR_NORM_BAND_UNAVAILABLE`. If it holds no rows at all, the earlier and more general `ERR_NO_TEST_RESULTS` applies.

A successful battery finalize propagates to the athlete: `last_composite_percentile` takes the new `composite_percentile`, `last_performance_test_at` takes the new `finalized_at`, and `next_test_due_on` becomes the date of that finalize plus the testing cadence of eight weeks — 56 days. Where an athlete has several finalized batteries, "the most recent" always means the one with the latest `finalized_at`, breaking ties by the later `created_at`. Then `readiness_index` is recomputed.

**The readiness index.** `readiness_index` is the facility's single gate number for competition-phase work, and it is evaluated live: it is recalculated on every test finalize, on every attendance or no-show, on every return-to-sport status change, on reinstatement, and — importantly — freshly against the current logical clock on every read of an athlete and on every enrollment attempt. Decay is therefore visible without any write occurring.

It is built in four movements and rounded half up to two decimal places at the end, confined to the closed range 0 through 100:

1. **Base.** The athlete's `last_composite_percentile`, or 50.0 when no battery has ever been finalized.
2. **Decay.** The number of whole days elapsed between `last_performance_test_at` and the current logical clock — computed by dividing the elapsed seconds by 86,400 and discarding the fraction, and taken as zero when `last_performance_test_at` is null. The first 30 days are a grace period and cost nothing; each day beyond the thirtieth costs 0.5 points, and the total decay is capped at 20.0 points, which the ladder reaches after 70 days beyond grace. Decay is subtracted from the base.
3. **Attendance adjustment.** When `attended_count` and `no_show_count` sum to zero, the adjustment is exactly 0.0 and no division is attempted. Otherwise the attendance rate is `attended_count` divided by the sum of `attended_count` and `no_show_count`, the target rate is 0.80, and the adjustment is 10 multiplied by the amount by which the rate exceeds the target, rounded half up to one decimal place before it is used. An athlete attending better than four sessions in five gains points; an athlete below that loses them, because the difference is negative.
4. **Return-to-sport penalty.** A flat 15.0 points are subtracted while the athlete holds a return-to-sport plan in `STAGE_ACTIVE`, `STAGE_TESTING` or `MEDICAL_REVIEW`; otherwise nothing is subtracted.

Enrollment in a session whose `phase_focus` is `COMPETITION` requires the athlete's live `readiness_index` to be at least 60.00 — the boundary is inclusive, so exactly 60.00 is admitted. Below it, the enrollment is refused with `ERR_READINESS_BELOW_THRESHOLD`.

**Progress reporting to athletes and parents.** The progress report is a pure computed read available to the `PerformanceDirector`, a `Coach`, and the athlete or their `Guardian`. It considers only `FINALIZED` `PERFORMANCE_BATTERY` sessions for that athlete; `DRAFT` sessions and movement screens never enter the ordering. Those sessions are ordered by `finalized_at` descending, breaking ties by `created_at` descending. From that ordering the report exposes `composite_percentile_current` (the newest session's composite, or null when there is none), `composite_percentile_previous` (the second newest, or null when fewer than two exist), and `delta_percentile_points` — the previous subtracted from the current, rounded half up to one decimal place, and null whenever either side is null. `tests_included_count` is how many finalized batteries the ordering contains. `normative_cohort` is a string formed from the band that scored the newest session, joining its sport, its position and its age band as sport, then position, then the band minimum and maximum separated by a hyphen, all separated by slashes — for instance `BASKETBALL/GUARD/15-16` — and null when no battery has been finalized. `readiness_index` is the live value. `attendance_rate_pct` is 100 multiplied by `attended_count` divided by the sum of `attended_count` and `no_show_count`, rounded half up to one decimal place, and null when that sum is zero. `next_test_due_on` is echoed from the athlete, and `test_overdue` is true exactly when `next_test_due_on` is not null and the current logical date is strictly later than it. The report also carries `athlete_id` and the fee statement described in §3.8.

### 3.3. Periodized Program Design

A **training program** is the periodization plan for one athlete against one competitive calendar. The `PerformanceDirector` or a `Coach` creates it with the `athlete_id`, a `sport` that must equal the athlete's current `sport`, a `position` that must equal the athlete's current `position`, and the calendar window bounded by `competition_start_date` and `competition_end_date`, both `YYYY-MM-DD` dates, with the end strictly later than the start. A new program is `DRAFT` with `block_count` and `total_weeks` at 0, `planned_load_units` at 0, and `pinned_block_versions` and `activated_at` null. A `SUSPENDED` athlete cannot have a program activated for them, which surfaces as `ERR_ATHLETE_SUSPENDED`.

**Blocks form one unbroken chain.** Each `ProgramBlock` belongs to a program through `training_program_id`, which is taken from the addressed program rather than from the body. A block declares a `phase` from `GENERAL_PREP`, `SPECIFIC_PREP`, `COMPETITION`, `TAPER` or `TRANSITION`; a one-based inclusive `start_week` of at least 1; an inclusive `end_week` no earlier than `start_week`; a `target_intensity_pct` expressing prescribed intensity as a percentage of the one-repetition-maximum equivalent, rejected if below 40 or above 105; and a strictly positive `weekly_volume_units` giving the prescribed weekly volume load. `predecessor_block_id` is optional and defaults to null, which marks the root of the chain. The append also carries `expected_training_program_version`, the concurrency guard of §2.6.

Chain integrity is checked both when a block is appended and again when the program is activated, and any violation returns `ERR_PROGRAM_BLOCK_SEQUENCE_INVALID`. The first block must have a null `predecessor_block_id` and must start at week 1. Every later block must name as its predecessor an existing block of the same program — of any `status`, since blocks are created `PLANNED` and only reach `PINNED` at activation, so the predecessor's status is never part of this check — must be the only block referencing that predecessor, and must have a `start_week` exactly one greater than the predecessor's `end_week`. A program with zero blocks cannot be activated. Each successful append creates the block with `status` of `PLANNED`, sets its `sequence_index` to the program's `block_count` before the append (so the root block is index 0 and each successor is one greater than its predecessor's index), advances `block_count` by one, recomputes `total_weeks`, and increments the program's `version` by one. `pinned_block_versions` stays null until activation.

**Activation.** Only the `PerformanceDirector` may activate, and only from `DRAFT`. Activation requires at least two blocks; exactly one block with a null `predecessor_block_id`; a single chain with no branch and no cycle; a `start_week` on every non-root block equal to its predecessor's `end_week` plus one; at least one block whose `phase` is `COMPETITION`; and an athlete whose `training_clearance` is not `MEDICAL_HOLD`. On success every block of the program moves from `PLANNED` to `PINNED`, and `pinned_block_versions` captures a snapshot array pairing each `program_block_id` with the `pinned_version` it held at that instant. `activated_at` is stamped from the logical clock, and `version` increments.

Activation also computes the plan's training load. **The rounding order is pinned:** each block's contribution is its `weekly_volume_units` multiplied by its week count — the `end_week` minus the `start_week`, plus one — multiplied by its `target_intensity_pct` divided by 100, and that per-block product is rounded half up to two decimal places *before* being added in. The rounded contributions are then summed, walking the blocks in ascending `sequence_index` order starting from the root, to give `planned_load_units`. `total_weeks` is the largest `end_week` among the program's blocks minus the smallest `start_week`, plus one, and is 0 while the program has no blocks.

An athlete runs at most one live plan. When a program becomes `ACTIVE`, any other program of the same athlete that was `ACTIVE` is moved to `ARCHIVED`, retaining its own `pinned_block_versions` as the historical record. `ARCHIVED` is terminal.

### 3.4. Coaching Staff, Certifications and Continuing Education

The `PerformanceDirector` registers each `StaffMember` with a `full_name`, a `role_title` of `HEAD_COACH`, `PERFORMANCE_COACH` or `INTERN`, and a `liability_insurance_expires_on` date in `YYYY-MM-DD` form. A newly registered staff member holds no certifications and their `credential_status` is `COMPLIANT`, with `valid_certification_count`, `lapsed_certification_count` and `ceu_credits_earned_total` at 0 and `last_credential_review_at` null.

Whenever `credential_status` is subsequently re-derived — at certification creation, at renewal, and at credential review — it is decided in this order: it becomes `LAPSED` when `lapsed_certification_count` is 1 or more, **or** when `liability_insurance_expires_on` falls earlier than the current logical date, **or** when `valid_certification_count` is 0; failing that it becomes `EXPIRING` when at least one of the staff member's certifications is `EXPIRING`; and otherwise it becomes `COMPLIANT`. `valid_certification_count` counts certifications whose `status` is `VALID` or `EXPIRING`; `lapsed_certification_count` counts those whose `status` is `LAPSED`; and `ceu_credits_earned_total` is the sum of `ceu_credits_earned` across the staff member's certifications.

**Certifications.** A certification records a `staff_member_id`, a `cert_code` from `CSCS`, `USAW`, `CPR_AED` or `SCCC`, an `issued_on` date, an `expires_on` date that must be strictly later than `issued_on`, and a `ceu_credits_required` count of continuing-education credits needed for renewal, accepted from 0 through 40 and defaulting to 6. New certifications are created `VALID`, with `ceu_credits_earned` at 0 and `renewal_count` at 0, and they raise the owner's `valid_certification_count`.

Credits are logged against a certification by the `PerformanceDirector` or a `Coach`, supplying a `credits` amount that is added to the certification's `ceu_credits_earned` and to the staff member's `ceu_credits_earned_total`.

**Credential review is the only clock reconciliation for certifications.** A `PerformanceDirector` runs a review on a staff member, and it is the sole operation that re-evaluates certification status against the logical clock. Advancing the clock alone never lapses anything. The review walks the staff member's certifications in ascending `created_at` order and re-derives each one: an `expires_on` earlier than today makes it `LAPSED`; an `expires_on` from today through today plus 30 days inclusive makes it `EXPIRING`; anything further out makes it `VALID`. It then recomputes `valid_certification_count`, `lapsed_certification_count` and `ceu_credits_earned_total`, re-derives `credential_status`, and stamps `last_credential_review_at` from the clock.

When that review drives `credential_status` to `LAPSED`, a four-step cascade follows, and every step is part of the contract:

1. Because the certification lapsed, the owner's `lapsed_certification_count` rises and `credential_status` becomes `LAPSED`.
2. Because `credential_status` became `LAPSED`, the staff member is removed from `assigned_staff` on every group session whose `session_status` is `SCHEDULED` or `ROSTER_LOCKED` and whose `start_at` is later than the current logical clock, which lowers each of those sessions' `compliant_coach_count`.
3. Because `compliant_coach_count` fell below `required_coach_count`, each affected session's `staffing_status` becomes `UNDERSTAFFED`.
4. Because `staffing_status` became `UNDERSTAFFED`, each affected session that was `ROSTER_LOCKED` reverts to `SCHEDULED`, and every `RESERVED` enrollment on it has its `station_number` cleared to null.

**Renewal.** The `PerformanceDirector` renews a certification by supplying `new_expires_on`. Renewal is accepted from `VALID`, `EXPIRING` or `LAPSED`, and in every case requires `ceu_credits_earned` to have reached at least `ceu_credits_required` at the moment of renewal; falling short returns `ERR_CEU_REQUIREMENT_NOT_MET`. The two paths back to `VALID` differ in how far out the new expiry must sit, and both are enforced:

- From `LAPSED` to `VALID`, `new_expires_on` must be later than the current logical date.
- From `EXPIRING` to `VALID`, `new_expires_on` must be more than 30 days beyond the current logical date — otherwise the certification would immediately re-derive as `EXPIRING` again.

On success `expires_on` is replaced by `new_expires_on`, `renewal_count` rises by one, `ceu_credits_earned` is reset to 0 and the owner's `ceu_credits_earned_total` is re-derived as the sum across their certifications, and `credential_status` is recomputed on exactly the same rules the review uses — so a formerly `LAPSED` staff member returns to `COMPLIANT` provided no other certification is `LAPSED` and their insurance is still live. When `credential_status` returns to a non-lapsed value, every group session the staff member is still assigned to recomputes its coaching requirement and may move from `UNDERSTAFFED` back to `STAFFED`.

Two gates depend on all of this. A staff member whose persisted `credential_status` is `LAPSED`, or whose `liability_insurance_expires_on` is earlier than the current logical date, may neither be assigned to a group session nor administer a test session; both attempts return `ERR_STAFF_CREDENTIAL_LAPSED`. On a coach assignment that credential defect is reported **before** any scheduling-overlap or travel-buffer evaluation on the same request.

### 3.5. Scheduling Group Sessions: Staffing, Ratios and Station Rotation

The `PerformanceDirector` or a `FrontDesk` operator schedules a **group session** by giving its `start_at` and `end_at` as ISO 8601 UTC instants with the end strictly after the start, a `site_code` of `ONSITE` or `OFFSITE`, a `station_count` from 1 through 12 describing how many equipment stations the rotation uses, a `phase_focus` of `GENERAL_PREP`, `SPECIFIC_PREP`, `COMPETITION` or `TRANSITION`, and a `max_athletes` roster capacity from 1 through 40. Two optional fields complete it: `offsite_location`, the travel-training venue label, which is **required** and non-empty when `site_code` is `OFFSITE` and must be absent or null when `site_code` is `ONSITE`; and `team_contract_id`, set when the session is delivered under a school or club contract. A session may reference a contract only while that contract's `status` is `ACTIVE`, and otherwise the request fails with `ERR_CONTRACT_NOT_ACTIVE`.

Occupancy is measured on the half-open interval that runs from `start_at` up to but not including `end_at`. That is what makes back-to-back scheduling legal. At most three non-canceled `ONSITE` sessions may have overlapping half-open intervals — the cap is aggregate across every contract and every athlete, not per contract — and a fourth overlapping onsite session is refused with `ERR_SITE_CONCURRENCY_EXCEEDED`.

A newly scheduled session has `session_status` of `SCHEDULED` and `staffing_status` of `STAFF_PENDING`, with `assigned_staff` empty, all four enrollment counters (`reserved_count`, `waitlisted_count`, `attended_count`, `no_show_count`) at 0, `athlete_units` at 0, `compliant_coach_count` at 0, and the billing snapshot fields `billed_rate_cents`, `rate_tier_applied` and `delivered_slots_at_completion` all null, as is `cancel_reason`. Its `required_coach_count` is computed immediately from `station_count` alone, since no athletes are enrolled yet.

**The coaching requirement.** `required_coach_count` is recomputed whenever an enrollment is created, whenever an enrollment changes status, whenever a coach is assigned, and whenever an assigned staff member's `credential_status` changes. It rests on a weighted count of athletes rather than a headcount, because a twelve-year-old and a rehabilitating athlete each demand more supervision than a healthy senior. For each enrollment on the session whose `status` is `RESERVED` or `ATTENDED` — `WAITLISTED`, `NO_SHOW`, `LATE_CANCEL` and `CANCELED` rows are excluded — the athlete contributes units by the **first matching** of these three branches: 2.5 units if the athlete holds a return-to-sport plan in `STAGE_ACTIVE`, `STAGE_TESTING` or `MEDICAL_REVIEW`; otherwise 1.5 units if their `age_years` is 12 or under; otherwise 1.0 unit. Those contributions are summed and rounded half up to one decimal place to give `athlete_units`.

Two independent requirements are then derived and the larger wins. The **ratio requirement** divides `athlete_units` by the base ratio for the site — one coach per 8 athlete-units `ONSITE`, but only one coach per 4 athlete-units `OFFSITE`, since travel training halves the tolerable span of control — and rounds the quotient up to a whole coach. The **station requirement** divides `station_count` by 3, the number of equipment stations one coach can supervise, and likewise rounds up. `required_coach_count` is the greatest of 1, the ratio requirement, and the station requirement, so every session needs at least one coach no matter how empty it is.

`compliant_coach_count` counts the rows of `assigned_staff` whose staff member's `credential_status` is anything other than `LAPSED`. `staffing_status` follows mechanically: `STAFF_PENDING` while `assigned_staff` is empty and `compliant_coach_count` is 0; `UNDERSTAFFED` when `compliant_coach_count` is below `required_coach_count`; and `STAFFED` otherwise. The `STAFF_PENDING` reading is reserved for a session that has never had a coach taken off it: once the credential-lapse cascade of §3.4 has actually removed a staff member from a session's `assigned_staff`, that session never reads `STAFF_PENDING` again even if `assigned_staff` is empty once more — it reads `UNDERSTAFFED` for as long as `compliant_coach_count` stays below `required_coach_count`, exactly as §3.4 step 3 requires, and `STAFFED` once enough compliant coaches are assigned to meet the requirement.

**Assigning coaches.** The `PerformanceDirector` or `FrontDesk` assigns a coach by naming a `staff_member_id` together with `expected_group_session_version`. Each row appended to `assigned_staff` records that `staff_member_id` and a `coach_role` of `LEAD` or `ASSISTANT`. The assignment increments the session's `version` by one, recomputes the coaching requirement, and moves `staffing_status` accordingly: `STAFF_PENDING → STAFFED` when the resulting `compliant_coach_count` reaches `required_coach_count`; `STAFF_PENDING → UNDERSTAFFED` when it reaches at least 1 but still falls short of `required_coach_count`; and `UNDERSTAFFED → STAFFED` when it catches up. **Over-staffing is explicitly permitted**: assigning a further compliant coach to a session that is already `STAFFED` is a valid `STAFFED → STAFFED` self-transition that simply raises `compliant_coach_count` and increments `version`, and it must never be rejected as an invalid state. Assignment is only accepted while `session_status` is `SCHEDULED`.

Three checks guard an assignment beyond the credential gate of §3.4, in this order: the credential defect first, then the scheduling overlap, then the travel buffer. A staff member may not hold two assignments whose intervals overlap when treated as **closed** intervals — endpoints included — which returns `ERR_STAFF_SCHEDULE_CONFLICT`; sessions that merely touch at an endpoint while sharing the same `site_code` and the same `offsite_location` do not conflict. And consecutive assignments at *different* locations — a differing `site_code`, or both `OFFSITE` with differing `offsite_location` — require a gap of at least 30 minutes between the earlier session's `end_at` and the later session's `start_at`, failing which the assignment is refused with `ERR_TRAVEL_BUFFER_VIOLATION`.

Movement in the other direction is automatic. A session sitting at `STAFFED` drops to `UNDERSTAFFED` whenever `compliant_coach_count` falls below `required_coach_count` — either because a new enrollment grew `athlete_units` past what the assigned coaches can cover, or because an assigned staff member's `credential_status` became `LAPSED`. When that drop happens to a session whose `session_status` is `ROSTER_LOCKED`, the session reverts `ROSTER_LOCKED → SCHEDULED` and every `RESERVED` enrollment on it has its `station_number` cleared to null.

**Locking the roster and assigning stations.** The `PerformanceDirector`, a `Coach` or a `FrontDesk` operator locks the roster, moving `session_status` from `SCHEDULED` to `ROSTER_LOCKED`. Three preconditions apply: the session must be `SCHEDULED`, its `staffing_status` must be `STAFFED`, and it must hold at least one `RESERVED` enrollment. Locking while `staffing_status` is anything other than `STAFFED` is refused with `ERR_COACH_RATIO_EXCEEDED`, and locking after the session's `start_at` has been reached is refused with `ERR_ENROLLMENT_WINDOW_CLOSED`.

The lock is what distributes athletes around the equipment. The session's `RESERVED` enrollments are ordered by ascending `created_at` — no further tie-break is needed, because `created_at` is stamped to millisecond precision and never repeats within a session — and then walked with a zero-based counter. Each enrollment's `station_number` is one plus the remainder of dividing its counter position by the session's `station_count`, so the first athlete takes station 1, the athlete after the last station wraps back to station 1, and every station index falls between 1 and `station_count`. `WAITLISTED` enrollments receive no station and keep `station_number` null. Locking increments the session's `version` by one.

**Starting.** A `Coach` starts a session, moving `session_status` from `ROSTER_LOCKED` to `IN_PROGRESS`. The session must be `ROSTER_LOCKED`, its `staffing_status` must still be `STAFFED`, and the current logical clock must have reached or passed `start_at`. Starting increments `version`. Once a session is `IN_PROGRESS`, enrollments can no longer be created on it or cancelled from it.

**Cancelling a session.** The `PerformanceDirector` or `FrontDesk` cancels a session from either `SCHEDULED` or `ROSTER_LOCKED`, recording a free-text `cancel_reason` on the session. Both source states drive `session_status` to `CANCELED`, which is terminal, and both run the same refund chain: every enrollment on the session whose `status` is `RESERVED` or `WAITLISTED` becomes `CANCELED` with an enrollment-level `cancel_reason` of `SESSION_CANCELED`, and its funding is returned to its source — a package credit restored with `DEPLETED` reverting to `ACTIVE` where applicable, or a contract slot restored including the `offsite_sessions_used` decrement for an offsite session. No strike is recorded and no fee is charged against any athlete. The only difference between the two source states is that cancelling from `ROSTER_LOCKED` additionally clears `station_number` to null on the affected enrollments, since stations had already been handed out. Cancellation increments the session's `version`.

### 3.6. Funding Instruments: Team Contracts and Membership Packages

Two instruments pay for training, and the enrollment waterfall of §3.7 consults them in a fixed order.

**Team contracts with schools and clubs.** The `PerformanceDirector` creates a contract with an `organization_name`, an `organization_type` of `SCHOOL` or `CLUB`, a `contracted_sessions` count of athlete session slots purchased (from 1 through 500), an undiscounted `base_rate_cents` per slot that may not be negative, an `offsite_allowance` capping how many travel-training slots the contract may fund (at least 0, defaulting to 0), and a term bounded by `term_start` and `term_end`, where `term_end` may not fall earlier than `term_start`. A new contract is `DRAFT` with `sessions_available` seeded to `contracted_sessions`, `sessions_reserved`, `sessions_delivered`, `offsite_sessions_used` and `billed_amount_cents` at 0, and `rate_tier` at `TIER_1`.

Activation by the `PerformanceDirector` requires the contract to be `DRAFT` and its `term_end` to be later than the current logical date; on success `status` moves `DRAFT → ACTIVE` and `sessions_available` is set to `contracted_sessions`. Only then are its slots spendable and its sessions billable. Linking a roster athlete to a contract — done by the `PerformanceDirector` or `FrontDesk` with the athlete's `athlete_id` — likewise requires the contract to be `ACTIVE`, failing which the link is refused with `ERR_CONTRACT_NOT_ACTIVE`. The link writes `team_contract_id` on the athlete, which is what puts contract slots at the head of that athlete's funding waterfall.

`rate_tier` is a derived view of volume delivered: `TIER_1` while `sessions_delivered` is under 2, `TIER_2` while it is at least 2 and under 5, and `TIER_3` from 5 upward. `CLOSED` is likewise derived rather than terminal. When a completion raises `sessions_delivered` to exactly `contracted_sessions`, `status` moves `ACTIVE → CLOSED` and the contract leaves the funding candidate pool; when a later void-completion lowers `sessions_delivered` back below `contracted_sessions`, `status` moves `CLOSED → ACTIVE` and the contract reopens.

**Membership packages.** A `FrontDesk` operator sells a package to an athlete, naming the `athlete_id`, a `sessions_purchased` credit count from 1 through 100, a `price_cents` amount paid that may not be negative, and a contractual `expires_on` date that may not fall earlier than the current logical date. The package opens `ACTIVE` with `sessions_remaining` equal to `sessions_purchased`; `sessions_reserved`, `sessions_consumed`, `sessions_forfeited` and `frozen_days_total` at 0; `frozen_at` null; and `effective_expires_on` equal to `expires_on`. A `SUSPENDED` athlete cannot be sold a package, which returns `ERR_ATHLETE_SUSPENDED`.

The four spend counters plus `sessions_remaining` form a **conservation identity**: every credit ever purchased is at all times either remaining, reserved by a held enrollment, consumed by an attended session, or forfeited. Credits move between these buckets and are never created or destroyed. Reservation moves a credit from `sessions_remaining` to `sessions_reserved`; attendance moves it from `sessions_reserved` to `sessions_consumed`; a no-show or a late cancellation moves it from `sessions_reserved` to `sessions_forfeited`; a refund moves it from `sessions_reserved` back to `sessions_remaining`; and an expiry sweep moves the whole remainder from `sessions_remaining` to `sessions_forfeited`.

`status` tracks that ledger. A package moves `ACTIVE → DEPLETED` at the moment a reservation takes its last remaining credit, leaving `sessions_remaining` at 0, and moves `DEPLETED → ACTIVE` again as soon as a refund — from a timely enrollment cancellation, a suspension cascade, or a session cancellation — restores at least one credit. `EXPIRED` is terminal and is reached only through the clock sweep of §2.4, from `ACTIVE`, `FROZEN` or `DEPLETED`; from `ACTIVE` and `FROZEN` the sweep also forfeits the remainder, while a `DEPLETED` package has nothing left to forfeit.

**Freezing and the expiry credit.** A `FrontDesk` operator freezes an `ACTIVE` package, which stamps `frozen_at` from the logical clock, moves `status` to `FROZEN`, and takes the package out of the funding candidate pool entirely. Only a `FROZEN` package can be unfrozen; an `ACTIVE` package cannot be unfrozen and a `FROZEN` package cannot be frozen again, both of which return `ERR_INVALID_STATE`, while any operation against an `EXPIRED` package returns `ERR_ALREADY_TERMINAL`. Unfreezing returns `status` to `ACTIVE`, clears `frozen_at` to null, and credits the frozen time back to the athlete: the elapsed seconds between `frozen_at` and the unfreeze instant are divided by 86,400 and **rounded up**, so any partial day counts as a full day, and the result is added to `frozen_days_total`. `effective_expires_on` is then recomputed as `expires_on` advanced by `frozen_days_total` whole days. Because `frozen_days_total` accumulates across successive freezes in unfreeze order, a package frozen and unfrozen repeatedly carries the sum of all its frozen days.

Note the asymmetry that follows from §2.4: `effective_expires_on`, not `expires_on`, is what the expiry sweep and the funding waterfall test.

### 3.7. Enrollment: the Funding Waterfall, Capacity and the Waitlist

An enrollment is booked by a `FrontDesk` operator, a `Coach`, the athlete themselves, or their `Guardian`, naming the `athlete_id` and the `group_session_id`. Two optional fields shape the outcome. `funding_preference` is `ANY`, `PACKAGE_ONLY` or `DROP_IN_OK` and defaults to `ANY`; `PACKAGE_ONLY` forbids the drop-in bucket entirely. `request_waitlist` is a boolean defaulting to false; when true, a capacity or coach-ratio breach produces a `WAITLISTED` row instead of an error.

A long list of gates precedes any funding decision, and their relative order is what determines which error a client sees. A `SUSPENDED` athlete is refused with `ERR_ATHLETE_SUSPENDED` before any funding, ratio, safety or temporal evaluation. An athlete already holding an enrollment on this same session in `RESERVED`, `WAITLISTED`, `ATTENDED` or `NO_SHOW` state is refused with `ERR_DUPLICATE_ENROLLMENT` — at most one such row may exist per athlete per session. An athlete still at `SCREEN_PENDING` is refused with `ERR_MOVEMENT_SCREEN_REQUIRED`, and one at `MEDICAL_HOLD` with `ERR_ATHLETE_MEDICAL_HOLD`. Next come the business constraints: **capacity is evaluated before the coaching ratio**, because capacity is a fixed property of the session while the ratio depends on who else happens to be enrolled. A session whose `reserved_count` already equals `max_athletes` refuses the booking with `ERR_SESSION_FULL` unless `request_waitlist` is true. A booking that would push the recomputed `required_coach_count` above the session's current `compliant_coach_count` refuses with `ERR_COACH_RATIO_EXCEEDED`, again unless `request_waitlist` is true. A `RESTRICTED` athlete may only be enrolled in sessions whose `phase_focus` is `GENERAL_PREP` or `TRANSITION`; `COMPETITION`, `SPECIFIC_PREP` and `TAPER` sessions are refused with `ERR_RESTRICTED_PHASE_NOT_PERMITTED`. And a `COMPETITION` session applies the readiness gate of §3.2.

The temporal gates follow. An athlete may not hold two `RESERVED` or `WAITLISTED` enrollments in sessions whose half-open intervals overlap, which returns `ERR_ATHLETE_SCHEDULE_CONFLICT`; back-to-back sessions are permitted precisely because the interval excludes its own end. And enrollment closes once the session's `start_at` is at or before the current logical clock, which returns `ERR_ENROLLMENT_WINDOW_CLOSED`.

**The funding waterfall.** A row entering `RESERVED` runs a three-bucket waterfall that writes its `funding_source`, its `membership_package_id` and its `charge_cents`. Buckets are tried strictly in order.

*Bucket one — the team contract*, always preferred when eligible. It applies when the athlete's `team_contract_id` is not null, the contract's `status` is `ACTIVE`, its `sessions_available` is at least 1, the session's start date falls within the contract's `term_start` through `term_end` inclusive, and either the session is `ONSITE` or the contract's `offsite_sessions_used` is still below its `offsite_allowance`. On a match, `funding_source` becomes `TEAM_CONTRACT` and `charge_cents` is 0; the contract's `sessions_available` drops by one and its `sessions_reserved` rises by one; and for an `OFFSITE` session its `offsite_sessions_used` also rises by one. A contract-linked athlete whose contract is `ACTIVE` but whose `offsite_sessions_used` has already reached `offsite_allowance` cannot consume a contract slot for an offsite session, and that condition is reported as `ERR_OFFSITE_ALLOWANCE_EXHAUSTED` rather than silently falling through to the package bucket.

*Bucket two — a membership package.* Candidates are the athlete's packages whose `status` is `ACTIVE`, whose `sessions_remaining` is at least 1, and whose `effective_expires_on` is on or after the session's start date. `FROZEN`, `DEPLETED` and `EXPIRED` packages are excluded from the pool. Candidates are ranked by `effective_expires_on` ascending, breaking ties by `created_at` ascending, so the credit closest to expiring is always spent first. The winner sets `funding_source` to `MEMBERSHIP_PACKAGE`, records its own id as `membership_package_id`, and leaves `charge_cents` at 0; its `sessions_remaining` drops by one, its `sessions_reserved` rises by one, and if that leaves `sessions_remaining` at 0 the package moves to `DEPLETED`.

*Bucket three — drop-in cash.* Reached only when neither earlier bucket resolved. If `funding_preference` is `PACKAGE_ONLY`, this bucket is closed and the enrollment is refused rather than charged. Otherwise `funding_source` becomes `DROP_IN` and `charge_cents` is the drop-in rate of 4,500 cents, plus an offsite surcharge of 1,500 cents when the session's `site_code` is `OFFSITE`.

Two fiscal refusals need distinguishing, because they answer different questions. `ERR_NO_SESSION_CREDIT` is reserved for the athlete who owns **no** package at all and has no eligible contract slot, while asking for `PACKAGE_ONLY` funding. `ERR_PACKAGE_EXPIRED` takes precedence over it whenever the athlete does own at least one package but every candidate is rejected purely on date grounds — an `effective_expires_on` earlier than the session date — or is already `EXPIRED`, and no other bucket may be used.

**Waitlisting and promotion.** A row is created `WAITLISTED` instead of `RESERVED` when `request_waitlist` is true **and** either `reserved_count` already equals `max_athletes` or the coach-ratio check would fail. `WAITLISTED` rows run no funding allocation whatsoever: their `funding_source` stays `UNFUNDED`, `charge_cents` stays 0, `membership_package_id` stays null, and `station_number` stays null. They also increment the session's `waitlisted_count` rather than its `reserved_count`.

Every event that frees a `RESERVED` slot on a session still sitting at `SCHEDULED` or `ROSTER_LOCKED` — an enrollment cancellation, a late cancellation, a suspension cascade, or a medical-hold cascade — triggers promotion. While `reserved_count` remains below `max_athletes`, the server takes the `WAITLISTED` enrollment on that session with the earliest `created_at` and runs the funding waterfall for it against the state prevailing at promotion time, not at booking time. If a bucket resolves, that row moves `WAITLISTED → RESERVED`, `promoted_from_waitlist` is set to true, its `funding_source`, `membership_package_id` and `charge_cents` are written by the allocation, the session's `version` increments, and promotion stops — at most one enrollment is promoted per freed slot. If no bucket resolves, the row instead moves `WAITLISTED → CANCELED` with `cancel_reason` of `FUNDING_UNAVAILABLE`; the failure does **not** consume the freed slot, and the loop proceeds to the next candidate in ascending `created_at` order. A funding failure during promotion never surfaces as an error to any client, because no client made the request. Promotion halts when no `WAITLISTED` candidates remain.

**Cancelling an enrollment.** A `FrontDesk` operator, the athlete, or their `Guardian` cancels a held enrollment; the row must be `RESERVED` (or `WAITLISTED`, which may only ever be cancelled) and the session must still be `SCHEDULED` or `ROSTER_LOCKED`. The late-cancellation window is 24 hours. When the gap between the session's `start_at` and the current logical clock is 24 hours **or more**, the row becomes `CANCELED` with `cancel_reason` of `ATHLETE_REQUEST` and the credit is fully refunded: a package's `sessions_reserved` falls by one and `sessions_remaining` rises by one, returning a `DEPLETED` package to `ACTIVE`; a contract's `sessions_reserved` falls by one and `sessions_available` rises by one, with `offsite_sessions_used` also decremented for an offsite session. `station_number` is cleared to null, the session's `version` increments, and the freed slot goes to the waitlist.

When that gap is **less than** 24 hours, the row becomes `LATE_CANCEL` instead, still with `cancel_reason` of `ATHLETE_REQUEST`, and the credit is forfeited rather than refunded: a package's `sessions_reserved` falls by one and `sessions_forfeited` rises by one, while a contract's `sessions_reserved` falls by one and `sessions_delivered` rises by one — the facility counts the slot as delivered because the coach's time was reserved. No strike is recorded and `no_show_fee_cents` stays 0. The freed slot still triggers waitlist promotion. Cancelling a `WAITLISTED` row on the explicit path records `cancel_reason` of `ATHLETE_REQUEST`, distinguishing it from the `FUNDING_UNAVAILABLE` reason the promotion path writes. `NO_SHOW`, `LATE_CANCEL` and `CANCELED` are all terminal enrollment states.

### 3.8. Session Execution: Attendance, No-Shows, Completion and Void

**Attendance.** A `Coach` marks a `RESERVED` enrollment as attended while the session is `IN_PROGRESS`. `status` moves `RESERVED → ATTENDED`, the session's `attended_count` and the athlete's `attended_count` each rise by one, `readiness_index` is recomputed, and for a package-funded row the package's `sessions_reserved` falls by one while `sessions_consumed` rises by one. An enrollment must be `RESERVED` to be attended, marked as a no-show, or cancelled; anything else returns `ERR_INVALID_STATE`.

**The no-show ladder.** A `Coach` or `FrontDesk` operator may mark a `RESERVED` enrollment as a no-show while the session is `IN_PROGRESS` or `COMPLETED`, and completion sweeps the remainder automatically. The transition is deliberately expensive, and it cascades in a chain that runs three entities deep:

First the counters move. The athlete's `no_show_count` rises by one and their rolling `no_show_strikes` rises by one; the session's `no_show_count` rises by one; a package-funded row moves a credit from `sessions_reserved` to `sessions_forfeited`. The post-increment strike value is persisted on the enrollment as `strike_index_at_no_show`, because it is what sets the fee.

Then the fee is assessed. The list price of a session is 4,500 cents and the no-show fee is 27.5 per cent of it, scaled by a strike multiplier read from the post-increment strike index: a first or second strike carries a multiplier of 1.0, a third strike carries 1.5, and a fourth or any subsequent strike carries 2.0. The product of the list price, the fee percentage and the multiplier is rounded half up to whole cents and stored as `no_show_fee_cents`. A late cancellation never charges a fee and never records a strike, so `no_show_fee_cents` stays 0 on those rows.

Then, when the strike counter reaches 3, the athlete's membership machine fires. `membership_status` moves `ACTIVE → SUSPENDED` automatically, and its own side effects run: every enrollment of that athlete still `RESERVED` on a group session whose `start_at` is later than the current logical clock becomes `CANCELED` with `cancel_reason` of `ATHLETE_SUSPENDED`; each of those cancellations refunds its funding source — a package's `sessions_reserved` falls by one and `sessions_remaining` rises by one, a contract's `sessions_reserved` falls by one and `sessions_available` rises by one with `offsite_sessions_used` also decremented for an offsite session; and each freed roster slot in turn triggers waitlist promotion on its own session. A single no-show can therefore promote a stranger onto a different session two steps away. Finally `readiness_index` is recomputed.

**The fee statement.** The progress report of §3.2 reports `no_show_fee_total_cents`, the athlete's lifetime-to-date no-show liability. **The rounding order is pinned:** each enrollment's `no_show_fee_cents` was already rounded to whole cents at the instant of its own no-show transition, and the statement simply **sums those persisted integers**. It performs no further rounding and no recomputation. The rejected alternative — recomputing each line unrounded, summing the unrounded lines, and rounding once at the end — is explicitly not the contract, and the two disagree: two lines at the base multiplier are 1,237.5 cents each, so per-line rounding totals 2,476 cents while sum-then-round totals 2,475. Only rows whose `status` is `NO_SHOW` contribute; `LATE_CANCEL` and `CANCELED` rows never do, and there is no time window — the statement is lifetime.

**Completion.** A `Coach` completes an `IN_PROGRESS` session. Three things happen in sequence. Every enrollment still `RESERVED` is swept to `NO_SHOW` in ascending `created_at` order, each one running the full no-show cascade above, fee and strike and possible suspension included. Every enrollment still `WAITLISTED` becomes `CANCELED` with `cancel_reason` of `SESSION_CANCELED`. Every package-funded `ATTENDED` or `NO_SHOW` row has its package's `sessions_reserved` decremented and its `sessions_consumed` incremented. Then `session_status` moves `IN_PROGRESS → COMPLETED` and `version` increments.

**Contract billing at completion.** When the completed session carries a `team_contract_id`, the contract is billed, and the **evaluation order is pinned** because the formula would otherwise be circular — the rate tier is keyed on the very delivered counter this completion is about to advance.

1. The contract's `sessions_delivered` is read **once, before any increment**. Call that the delivered-before figure.
2. The tier is chosen from that snapshot alone: `TIER_1` when the delivered-before figure is under 2, `TIER_2` when it is at least 2 and under 5, and `TIER_3` otherwise. The chosen tier is persisted on the session as `rate_tier_applied`.
3. One rate is computed for the whole completion — it is emphatically **not** re-tiered slot by slot. `billed_rate_cents` is the contract's `base_rate_cents` multiplied by the tier multiplier (1.00 for `TIER_1`, 0.92 for `TIER_2`, 0.85 for `TIER_3`), multiplied again by 1.20 when the session's `site_code` is `OFFSITE` and by 1 when it is `ONSITE` — travel training carries a 20 per cent premium — with the result rounded half up to whole cents.
4. `delivered_slots_at_completion` is the count of enrollments on this session whose `funding_source` is `TEAM_CONTRACT` and whose `status` is `ATTENDED` or `NO_SHOW`. `LATE_CANCEL` rows were already counted as delivered at cancellation time and are excluded here.
5. Only now do the contract counters advance: `sessions_reserved` falls by `delivered_slots_at_completion`, `sessions_delivered` rises by the same amount, and `billed_amount_cents` rises by `billed_rate_cents` multiplied by `delivered_slots_at_completion`. If `sessions_delivered` now equals `contracted_sessions` exactly, the contract's `status` moves `ACTIVE → CLOSED`.

**Voiding a completion.** Only the `PerformanceDirector` may reverse an erroneous completion, supplying a `void_reason`. The session must be `COMPLETED`, and the reversal is refused outright when **any** enrollment on the session was marked `NO_SHOW`, because the strike counters and the assessed fees against those athletes cannot be unwound; that refusal is `ERR_VOID_BLOCKED_BY_NO_SHOW`. On success `session_status` moves `COMPLETED → IN_PROGRESS`, and every `ATTENDED` enrollment reverts to `RESERVED` with the athlete's `attended_count` reduced by one for each and each package-funded row moving a credit from `sessions_consumed` back to `sessions_reserved`.

The contract reversal **must use the stored snapshots** and never a recomputed rate: `billed_amount_cents` is reduced by the persisted `billed_rate_cents` multiplied by the persisted `delivered_slots_at_completion`, `sessions_delivered` is reduced by `delivered_slots_at_completion`, and `sessions_reserved` is increased by the same amount. Recomputing the tier at void time would drift the contract's billed total whenever an intervening completion had moved the tier. If `sessions_delivered` now falls below `contracted_sessions`, the contract moves `CLOSED → ACTIVE`. Finally `billed_rate_cents`, `rate_tier_applied` and `delivered_slots_at_completion` are all cleared to null, and the session's `version` increments.

### 3.9. Return-to-Sport Progressions and Medical Clearance

**Opening a progression.** Only a `MedicalProvider` may open a return-to-sport plan, naming the `athlete_id`, the anchoring `injury_record_id`, and a `target_stage_count` — the number of progression stages to complete before medical review — accepted from 3 through 5 and defaulting to 4. The anchoring injury record must belong to the same athlete, must carry `rts_required` of true, and must have `status` of `ACTIVE_REHAB`; at most one non-terminal plan may exist per injury record. A request failing any of those conditions is refused with `ERR_INVALID_STATE`. The new plan opens `STAGE_ACTIVE` with `current_stage` at 1, `stage_attempts` at 0, `total_failed_attempts` at 0, `active_stage_test_id` null and `cleared_at` null.

Opening a plan immediately narrows the athlete's world. `training_clearance` moves `CLEARED → RESTRICTED` — this path needs no precondition beyond the plan creation succeeding — so from that moment the athlete may only be enrolled in `GENERAL_PREP` or `TRANSITION` sessions and needs a signed stage clearance to progress. `readiness_index` is recomputed with the 15-point return-to-sport penalty applied, and the athlete's supervision weighting jumps to 2.5 units on every session they hold, which may push those sessions from `STAFFED` to `UNDERSTAFFED`.

**Stage testing is a revision loop.** A `Coach` opens the criterion test for the plan's current stage; the plan must be `STAGE_ACTIVE` and the acting staff member's `credential_status` must not be `LAPSED`. The operation moves the plan `STAGE_ACTIVE → STAGE_TESTING` and creates a fresh test session on the athlete's behalf: `battery_type` of `PERFORMANCE_BATTERY`, `status` of `DRAFT`, `athlete_id` taken from the plan, `rts_plan_id` pointing back at the plan, and `administered_by_staff_id` set to the acting coach's `X-User-ID` — the same identity that is then barred from judging the result. The plan's `active_stage_test_id` records the new session's id. That session is populated and finalized exactly like any other performance battery; once it is `FINALIZED` the plan becomes eligible for a decision, and its `active_stage_test_id` is unchanged by the finalize itself.

**Stage decisions.** A `MedicalProvider` records a `decision` of `PASS` or `FAIL` on a plan sitting in `STAGE_TESTING`. Three preconditions are common to every path: the plan must be `STAGE_TESTING`, the test session named by `active_stage_test_id` must be `FINALIZED`, and the acting `X-User-ID` must differ from that session's `administered_by_staff_id` or the decision is refused with `ERR_SEGREGATION_OF_DUTIES`. A `PASS` additionally requires a clearance document for this plan whose `document_type` is `STAGE_CLEARANCE`, whose `stage_number` equals the plan's `current_stage`, whose `status` is `SIGNED` and unrevoked, and whose `expires_on` is on or after the current logical date. A missing or unsigned or revoked document returns `ERR_STAGE_CLEARANCE_MISSING`; a document whose `expires_on` has already passed returns `ERR_CLEARANCE_EXPIRED`. This safety gate is evaluated **before** any staffing, ratio or scheduling constraint on the same request.

The maximum number of attempts allowed at any one stage is 2, and the four outcomes are these:

- **`PASS` below the final stage** (`current_stage` less than `target_stage_count`): `current_stage` rises by one, `stage_attempts` resets to 0, `active_stage_test_id` is cleared to null, and the plan returns `STAGE_TESTING → STAGE_ACTIVE` to begin the next stage.
- **`PASS` at the final stage** (`current_stage` equal to `target_stage_count`): the plan moves `STAGE_TESTING → MEDICAL_REVIEW` and `active_stage_test_id` is cleared to null.
- **First `FAIL` at a stage** (the attempt count after incrementing is still below 2): `stage_attempts` rises by one, `total_failed_attempts` rises by one, `current_stage` is unchanged, `active_stage_test_id` is cleared to null, and the plan returns `STAGE_TESTING → STAGE_ACTIVE` so the stage can be re-tested.
- **Second `FAIL` at the same stage** (the attempt count after incrementing reaches 2): `stage_attempts` rises by one, `total_failed_attempts` rises by one, `active_stage_test_id` is cleared to null, and the plan escalates `STAGE_TESTING → MEDICAL_REVIEW` rather than looping again.

`readiness_index` is recomputed after every decision. The `STAGE_ACTIVE → STAGE_TESTING → STAGE_ACTIVE` loop may therefore repeat within a stage and across stages.

**Clearance documents.** A `MedicalProvider` creates a document naming the `athlete_id`, the `document_type`, an `expires_on` validity end date, and — conditionally — the `rts_plan_id` and `stage_number`. `document_type` is one of three, and each has its own shape:

- `STAGE_CLEARANCE` authorises one stage of one plan. It **requires** a non-null `rts_plan_id` and a `stage_number` of at least 1.
- `FULL_RELEASE` closes out a plan. It **requires** a non-null `rts_plan_id` and its `stage_number` must be null.
- `MEDICAL_HOLD_RELEASE` lifts a medical hold on the athlete directly. Its `rts_plan_id` **must** be null and its `stage_number` must be null.

Every document is created `PENDING`, with `provider_license_id` and `signed_at` null. `PENDING` documents do nothing until signed.

**Signing.** A `MedicalProvider` signs a `PENDING` document, supplying the `provider_license_id` that is persisted on the document as the signing provider's licence. The document must be `PENDING` and its `expires_on` must be on or after the current logical date; an already-expired document is refused with `ERR_CLEARANCE_EXPIRED`. The segregation rules of §2.11 apply. On success `status` moves `PENDING → SIGNED` and `signed_at` is stamped from the logical clock, after which the effect depends on `document_type`:

- A signed `STAGE_CLEARANCE` changes no state anywhere. It simply becomes the precondition a `PASS` decision at that `stage_number` requires.
- A signed `FULL_RELEASE` drives its referenced plan `MEDICAL_REVIEW → CLEARED`, which requires the plan to be in `MEDICAL_REVIEW` and the document to reference that plan while still `PENDING`. `cleared_at` is stamped from the logical clock. Because the plan reached `CLEARED`, the anchoring injury record's `status` becomes `RESOLVED`; because the injury resolved and no other plan is open, the athlete's `training_clearance` moves `RESTRICTED → CLEARED`; and because the athlete is no longer in an open progression, `readiness_index` is recomputed without the return-to-sport penalty and the 2.5-unit supervision weighting stops applying. `CLEARED` is terminal for a plan.
- A signed `MEDICAL_HOLD_RELEASE` drives the athlete's `training_clearance` out of `MEDICAL_HOLD`, and the destination depends on the athlete's standing risk. When `injury_risk_score` is below 12.00 or is null, the athlete moves `MEDICAL_HOLD → CLEARED`; when `injury_risk_score` is 12.00 or higher, the athlete moves `MEDICAL_HOLD → RESTRICTED` instead. Either way `readiness_index` is recomputed. Both branches also require the document to be `PENDING` at the moment of signing.

**Revocation.** A `MedicalProvider` revokes a document that is `PENDING` or `SIGNED`, supplying a `revoke_reason`. `status` becomes `REVOKED`, which is terminal, alongside `EXPIRED`. A revoked `STAGE_CLEARANCE` no longer satisfies the `PASS` precondition for its `stage_number`. Revoking a `SIGNED` document additionally clears the athlete's forward book when that athlete has an open return-to-sport plan: every enrollment of theirs in `RESERVED` or `WAITLISTED` on a group session whose `start_at` is later than the current logical clock becomes `CANCELED` with `cancel_reason` of `ATHLETE_SUSPENDED` and has its funding refunded. Revoking a merely `PENDING` document carries no such cascade, since nothing had yet been authorised.

**Abandoning a progression.** Only a `MedicalProvider` may abort a plan, and only from `STAGE_ACTIVE`, `STAGE_TESTING` or `MEDICAL_REVIEW` — a plan already `CLEARED` or `ABORTED` is terminal. The request supplies an `abort_reason`. All three source states behave identically: `status` becomes `ABORTED`, which is terminal, `active_stage_test_id` is cleared to null, and the athlete's `training_clearance` is set to `MEDICAL_HOLD`. Every `RESERVED` or `WAITLISTED` future enrollment of the athlete becomes `CANCELED` with `cancel_reason` of `ATHLETE_SUSPENDED` and is refunded. Because the plan is no longer open, the return-to-sport readiness penalty and the 2.5-unit supervision weighting both stop applying, and every group session the athlete still holds recomputes its coaching requirement.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`: registering an athlete, recording an injury, opening a test session, creating a training program, appending a program block, scheduling a group session, creating an enrollment, registering a staff member, recording a certification, selling a membership package, creating a team contract, opening a return-to-sport plan, opening a stage criterion test (which mints the `TestSession` it returns), and creating a clearance document. Every other operation — including all reads, all state transitions, all counter mutations, and the logical-clock advance — returns `200 OK`.

| Method | Path                                                       | Description                                                                | Authorized Role(s)                                                        |
| ------ | ---------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| POST   | `/_clock/set_current_utc`                                  | Advance the logical UTC clock and run the expiry sweep                     | PerformanceDirector, Coach, MedicalProvider, FrontDesk                    |
| POST   | `/athletes`                                                | Register an athlete for intake                                             | FrontDesk, PerformanceDirector                                            |
| GET    | `/athletes/{athlete_id}`                                   | Read one athlete with live readiness                                       | PerformanceDirector, Coach, MedicalProvider, FrontDesk, Athlete, Guardian |
| GET    | `/athletes`                                                | List athletes with filters and pagination                                  | PerformanceDirector, Coach, MedicalProvider, FrontDesk                    |
| POST   | `/athletes/{athlete_id}/suspend`                           | Suspend an athlete's membership administratively                           | PerformanceDirector                                                       |
| POST   | `/athletes/{athlete_id}/reinstate`                         | Lift a suspension and reset the strike counter                             | PerformanceDirector                                                       |
| POST   | `/athletes/{athlete_id}/medical-hold`                      | Place an athlete on medical hold                                           | MedicalProvider                                                           |
| GET    | `/athletes/{athlete_id}/progress-report`                   | Computed progress report for athlete and parent reporting                  | PerformanceDirector, Coach, Athlete, Guardian                             |
| POST   | `/injury-records`                                          | Record an injury from history intake or a new incident                     | MedicalProvider, PerformanceDirector                                      |
| GET    | `/injury-records/{injury_record_id}`                       | Read one injury record                                                     | PerformanceDirector, Coach, MedicalProvider, Athlete, Guardian            |
| GET    | `/injury-records`                                          | List injury records                                                        | PerformanceDirector, Coach, MedicalProvider                               |
| POST   | `/injury-records/{injury_record_id}/resolve`               | Mark rehabilitation complete                                               | MedicalProvider                                                           |
| POST   | `/test-sessions`                                           | Open a draft test session                                                  | Coach                                                                     |
| POST   | `/test-sessions/{test_session_id}/results`                 | Submit the metric rows of a draft session                                  | Coach                                                                     |
| POST   | `/test-sessions/{test_session_id}/finalize`                | Finalize a draft session and score it                                      | Coach                                                                     |
| GET    | `/test-sessions/{test_session_id}`                         | Read one test session with its results and percentiles                     | PerformanceDirector, Coach, MedicalProvider, Athlete, Guardian            |
| GET    | `/test-sessions`                                           | List test sessions                                                         | PerformanceDirector, Coach, MedicalProvider                               |
| POST   | `/training-programs`                                       | Create a draft periodized program                                          | PerformanceDirector, Coach                                                |
| GET    | `/training-programs/{training_program_id}`                 | Read one program with its version and planned load                         | PerformanceDirector, Coach, Athlete, Guardian                             |
| GET    | `/training-programs`                                       | List training programs                                                     | PerformanceDirector, Coach                                                |
| POST   | `/training-programs/{training_program_id}/blocks`          | Append the next periodization block under optimistic concurrency           | PerformanceDirector, Coach                                                |
| POST   | `/training-programs/{training_program_id}/activate`        | Activate a draft program and compute its planned load                      | PerformanceDirector                                                       |
| GET    | `/program-blocks/{program_block_id}`                       | Read one periodization block                                               | PerformanceDirector, Coach, Athlete, Guardian                             |
| GET    | `/program-blocks`                                          | List periodization blocks                                                  | PerformanceDirector, Coach                                                |
| POST   | `/group-sessions`                                          | Schedule a group training session                                          | PerformanceDirector, FrontDesk                                            |
| GET    | `/group-sessions/{group_session_id}`                       | Read one session with staffing counters and billing snapshots              | PerformanceDirector, Coach, FrontDesk, Athlete, Guardian                  |
| GET    | `/group-sessions`                                          | List sessions, optionally within a time window                             | PerformanceDirector, Coach, FrontDesk                                     |
| POST   | `/group-sessions/{group_session_id}/coaches`               | Assign a coach under optimistic concurrency on the session version         | PerformanceDirector, FrontDesk                                            |
| POST   | `/group-sessions/{group_session_id}/lock-roster`           | Lock the roster and assign equipment stations                              | PerformanceDirector, Coach, FrontDesk                                     |
| POST   | `/group-sessions/{group_session_id}/start`                 | Start a roster-locked session                                              | Coach                                                                     |
| POST   | `/group-sessions/{group_session_id}/complete`              | Complete a session, sweep no-shows and bill the contract                   | Coach                                                                     |
| POST   | `/group-sessions/{group_session_id}/void-completion`       | Reverse an erroneous completion using the stored billing snapshots         | PerformanceDirector                                                       |
| POST   | `/group-sessions/{group_session_id}/cancel`                | Cancel a session and refund every held enrollment                          | PerformanceDirector, FrontDesk                                            |
| POST   | `/enrollments`                                             | Enrol an athlete, running the funding waterfall                            | FrontDesk, Coach, Athlete, Guardian                                       |
| GET    | `/enrollments/{enrollment_id}`                             | Read one enrollment with funding, station and fee detail                   | PerformanceDirector, Coach, FrontDesk, Athlete, Guardian                  |
| GET    | `/enrollments`                                             | List enrollments                                                           | PerformanceDirector, Coach, FrontDesk                                     |
| POST   | `/enrollments/{enrollment_id}/cancel`                      | Cancel a held enrollment, refunding or forfeiting by window                | FrontDesk, Athlete, Guardian                                              |
| POST   | `/enrollments/{enrollment_id}/attend`                      | Mark attendance on an in-progress session                                  | Coach                                                                     |
| POST   | `/enrollments/{enrollment_id}/no-show`                     | Mark a no-show, charging the fee and advancing the strike ladder           | Coach                                                                     |
| POST   | `/staff-members`                                           | Register a coaching staff member                                           | PerformanceDirector                                                       |
| GET    | `/staff-members/{staff_member_id}`                         | Read one staff member with credential counters                             | PerformanceDirector, Coach, FrontDesk                                     |
| GET    | `/staff-members`                                           | List staff members                                                         | PerformanceDirector, Coach, FrontDesk                                     |
| POST   | `/staff-members/{staff_member_id}/credential-review`       | Re-evaluate certifications against the clock and re-derive credentials     | PerformanceDirector                                                       |
| POST   | `/certifications`                                          | Record a professional certification                                        | PerformanceDirector                                                       |
| GET    | `/certifications/{certification_id}`                       | Read one certification                                                     | PerformanceDirector, Coach                                                |
| GET    | `/certifications`                                          | List certifications                                                        | PerformanceDirector, Coach                                                |
| POST   | `/certifications/{certification_id}/ceu-credits`           | Log continuing-education credits                                           | PerformanceDirector, Coach                                                |
| POST   | `/certifications/{certification_id}/renew`                 | Renew a certification once its CEU requirement is met                      | PerformanceDirector                                                       |
| POST   | `/membership-packages`                                     | Sell a session package to an athlete                                       | FrontDesk                                                                 |
| GET    | `/membership-packages/{membership_package_id}`             | Read one package with its credit ledger and effective expiry               | PerformanceDirector, FrontDesk, Athlete, Guardian                         |
| GET    | `/membership-packages`                                     | List membership packages                                                   | PerformanceDirector, FrontDesk                                            |
| POST   | `/membership-packages/{membership_package_id}/freeze`      | Freeze an active package                                                   | FrontDesk                                                                 |
| POST   | `/membership-packages/{membership_package_id}/unfreeze`    | Unfreeze a package and credit the frozen days to its expiry                | FrontDesk                                                                 |
| POST   | `/team-contracts`                                          | Create a draft school or club contract                                     | PerformanceDirector                                                       |
| GET    | `/team-contracts/{team_contract_id}`                       | Read one contract with its slot ledger and rate tier                       | PerformanceDirector, FrontDesk                                            |
| GET    | `/team-contracts`                                          | List team contracts                                                        | PerformanceDirector, FrontDesk                                            |
| POST   | `/team-contracts/{team_contract_id}/activate`              | Activate a draft contract so its slots become spendable                    | PerformanceDirector                                                       |
| POST   | `/team-contracts/{team_contract_id}/athletes`              | Link a roster athlete to an active contract                                | PerformanceDirector, FrontDesk                                            |
| POST   | `/rts-plans`                                               | Open a return-to-sport progression against an injury record                | MedicalProvider                                                           |
| GET    | `/rts-plans/{rts_plan_id}`                                 | Read one plan with its stage state                                         | PerformanceDirector, Coach, MedicalProvider, Athlete, Guardian            |
| GET    | `/rts-plans`                                               | List return-to-sport plans                                                 | PerformanceDirector, Coach, MedicalProvider                               |
| POST   | `/rts-plans/{rts_plan_id}/stage-test`                      | Open the criterion test for the plan's current stage                       | Coach                                                                     |
| POST   | `/rts-plans/{rts_plan_id}/stage-decision`                  | Record the medical pass-or-fail decision on the active stage test          | MedicalProvider                                                           |
| POST   | `/rts-plans/{rts_plan_id}/abort`                           | Abandon a return-to-sport progression                                      | MedicalProvider                                                           |
| POST   | `/clearance-documents`                                     | Create a pending clearance document                                        | MedicalProvider                                                           |
| GET    | `/clearance-documents/{clearance_document_id}`             | Read one clearance document                                                | PerformanceDirector, Coach, MedicalProvider, Athlete, Guardian            |
| GET    | `/clearance-documents`                                     | List clearance documents                                                   | PerformanceDirector, Coach, MedicalProvider                               |
| POST   | `/clearance-documents/{clearance_document_id}/sign`        | Sign a pending document and apply its release effect                       | MedicalProvider                                                           |
| POST   | `/clearance-documents/{clearance_document_id}/revoke`      | Revoke a pending or signed document                                        | MedicalProvider                                                           |

## 5. Error Code Catalogue

| Error ID                             | HTTP Status Code         |
| ------------------------------------ | ------------------------ |
| `ERR_UNAUTHENTICATED`                | 401 Unauthorized         |
| `ERR_UNAUTHORIZED`                   | 403 Forbidden            |
| `ERR_ATHLETE_SCOPE_VIOLATION`        | 403 Forbidden            |
| `ERR_SEGREGATION_OF_DUTIES`          | 403 Forbidden            |
| `ERR_ATHLETE_NOT_FOUND`              | 404 Not Found            |
| `ERR_INJURY_RECORD_NOT_FOUND`        | 404 Not Found            |
| `ERR_TEST_SESSION_NOT_FOUND`         | 404 Not Found            |
| `ERR_TRAINING_PROGRAM_NOT_FOUND`     | 404 Not Found            |
| `ERR_PROGRAM_BLOCK_NOT_FOUND`        | 404 Not Found            |
| `ERR_GROUP_SESSION_NOT_FOUND`        | 404 Not Found            |
| `ERR_ENROLLMENT_NOT_FOUND`           | 404 Not Found            |
| `ERR_STAFF_MEMBER_NOT_FOUND`         | 404 Not Found            |
| `ERR_CERTIFICATION_NOT_FOUND`        | 404 Not Found            |
| `ERR_MEMBERSHIP_PACKAGE_NOT_FOUND`   | 404 Not Found            |
| `ERR_TEAM_CONTRACT_NOT_FOUND`        | 404 Not Found            |
| `ERR_RTS_PLAN_NOT_FOUND`             | 404 Not Found            |
| `ERR_CLEARANCE_DOCUMENT_NOT_FOUND`   | 404 Not Found            |
| `ERR_INVALID_REQUEST`                | 422 Unprocessable Entity |
| `ERR_CLOCK_REWIND_FORBIDDEN`         | 422 Unprocessable Entity |
| `ERR_STALE_VERSION`                  | 412 Precondition Failed  |
| `ERR_INVALID_STATE`                  | 409 Conflict             |
| `ERR_ALREADY_TERMINAL`               | 409 Conflict             |
| `ERR_ATHLETE_SUSPENDED`              | 409 Conflict             |
| `ERR_DUPLICATE_ENROLLMENT`           | 409 Conflict             |
| `ERR_MOVEMENT_SCREEN_REQUIRED`       | 422 Unprocessable Entity |
| `ERR_ATHLETE_MEDICAL_HOLD`           | 422 Unprocessable Entity |
| `ERR_STAGE_CLEARANCE_MISSING`        | 422 Unprocessable Entity |
| `ERR_CLEARANCE_EXPIRED`              | 422 Unprocessable Entity |
| `ERR_STAFF_CREDENTIAL_LAPSED`        | 422 Unprocessable Entity |
| `ERR_CEU_REQUIREMENT_NOT_MET`        | 422 Unprocessable Entity |
| `ERR_SESSION_FULL`                   | 422 Unprocessable Entity |
| `ERR_COACH_RATIO_EXCEEDED`           | 422 Unprocessable Entity |
| `ERR_READINESS_BELOW_THRESHOLD`      | 422 Unprocessable Entity |
| `ERR_RESTRICTED_PHASE_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_PROGRAM_BLOCK_SEQUENCE_INVALID` | 422 Unprocessable Entity |
| `ERR_STAFF_SCHEDULE_CONFLICT`        | 409 Conflict             |
| `ERR_TRAVEL_BUFFER_VIOLATION`        | 409 Conflict             |
| `ERR_ATHLETE_SCHEDULE_CONFLICT`      | 409 Conflict             |
| `ERR_SITE_CONCURRENCY_EXCEEDED`      | 409 Conflict             |
| `ERR_ENROLLMENT_WINDOW_CLOSED`       | 409 Conflict             |
| `ERR_NORM_BAND_UNAVAILABLE`          | 422 Unprocessable Entity |
| `ERR_NO_TEST_RESULTS`                | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_ACTIVE`            | 422 Unprocessable Entity |
| `ERR_VOID_BLOCKED_BY_NO_SHOW`        | 409 Conflict             |
| `ERR_NO_SESSION_CREDIT`              | 402 Payment Required     |
| `ERR_PACKAGE_EXPIRED`                | 402 Payment Required     |
| `ERR_OFFSITE_ALLOWANCE_EXHAUSTED`    | 402 Payment Required     |
