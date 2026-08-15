# Therapy Animal Visits API — Product Requirements Document

## 1. Introduction

Therapy animal programs run on trust. Hospitals, schools, nursing homes, rehabilitation centers, and hospices open their doors to volunteer handler–animal teams only because a certifying organization stands behind every single visit — and that trust is operational, not abstract. It rests on temperament evaluations that genuinely predict bedside behavior, on rabies vaccinations and liability insurance that never lapse unnoticed, on rest rules and workload ceilings that protect the animal from overwork, on a disciplined incident process with segregated duties, and on a partnership contract that defines exactly what each facility permits. When any one of those pillars weakens, the program's license to operate weakens with it.

This document specifies the Therapy Animal Visits API, the system of record for such a certification and visit-scheduling program. It governs the full lifecycle: volunteer handler onboarding, animal registration, team formation, evaluated temperament testing with an appeal path, certification issuance and biennial renewal, facility partnership agreements and orientation, liability waivers and insurance adequacy, visit requests and team matching, the visit day itself from check-in to verified completion, volunteer-hour accounting with recognition tiers, and incident response with animal-welfare enforcement. All API paths are mounted under the `/v1` prefix. Every time-dependent rule in this document is evaluated against a server-maintained logical clock (§2.4), so renewal windows, offer expirations, rest blocks, and every scheduled sweep are deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity in which that party acts. A request missing either header, or carrying a role value outside the declared role set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles exist. `Anonymous` is the unauthenticated caller and may perform exactly one operation — self-registering as a handler. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity. `Handler` is the volunteer who owns animals, teams, vaccination records, insurance policies, and liability waivers, and who performs visits: when `X-User-Role` is `Handler`, `X-User-ID` is the `id` of the acting Handler record, and ownership checks on any resource that references a handler compare the resource's handler foreign-key field — an animal's, team's, or policy's `handler_id`, or the handler behind a visit's team — to `X-User-ID`. `Evaluator` is the certified temperament scorer: when `X-User-Role` is `Evaluator`, `X-User-ID` is the `id` of the acting Evaluator record, and the scoring operation compares the evaluation's assigned `evaluator_id` to `X-User-ID`. `FacilityCoordinator` is the facility-side counterpart: when `X-User-Role` is `FacilityCoordinator`, `X-User-ID` is the `id` of the coordinator's Facility record, and ownership checks on visit requests, orientation records, agreements, and visits compare the target resource's `facility_id` to `X-User-ID`. When `X-User-Role` is `ProgramAdmin` or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `triaged_by` or `resolved_by` on an incident report — but never compares it to any entity's `id`. Wherever an entity-backed actor touches a resource it does not own, the rejection is `ERR_OWNERSHIP_MISMATCH` (HTTP 403).

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

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at 100. `offset` sets the number of items skipped and defaults to 0. Unless a subsection states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Deterministic Sweeps

The server never consults wall-clock time. All date and timestamp comparisons in this document — every "today" and every "now" — read a logical clock maintained by the server. At startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. A ProgramAdmin-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant (ISO 8601 UTC) and answers with the resulting `current_utc`.

A second ProgramAdmin-only capability runs all deterministic time-based transitions in a single sweep, applied in a pinned order: outstanding offer expirations first, then stale visit-request expirations, then evaluation expirations (both unscheduled requests and lapsed appeal windows), then vaccination-record, insurance-policy, and orientation-record expirations, then certifications are marked due for renewal and overdue ones expired, then agreement expiration with its facility cascade, then visit no-show marking, then deemed-verified reconciliation, and finally welfare-hold auto-release. The sweep answers with per-category counts: `evaluations_expired`, `certifications_marked_renewal_due`, `certifications_expired`, `vaccinations_expired`, `policies_expired`, `orientations_expired`, `agreements_expired`, `offers_expired`, `requests_expired`, `visits_marked_no_show`, `visits_deemed_verified`, and `welfare_holds_released`.

### 2.5. Common Resource Properties

Every primary resource carries four system-managed properties. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording creation. `updated_at` follows the same format and is refreshed on any mutation of the resource. `version` is a system-managed integer that increments with every mutation. Any change to a resource — including derived recomputation such as a handler's lifetime minutes, an animal's workload counters, or a team's penalty counters — counts as a mutation that refreshes `updated_at` and increments `version`.

The hour-credit ledger row is the single exception. Because ledger rows are immutable once posted, an HourCredit carries only `id` and `created_at`; `updated_at` and `version` are absent from it.

### 2.6. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and for each the version field is a non-optional part of the request.

- Creating an offer against a visit request requires `expected_visit_request_version` carrying the client's last observed `version` of that request. If the request's current `version` does not match — because another writer has advanced it since the client last read the request — the offer is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Directly scheduling a visit requires `expected_team_version` carrying the client's last observed `version` of the team. If the team's current `version` does not match — because another booking has legitimately mutated the team's workload bookkeeping since the client last read it — the scheduling call is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these two accepts a version field; all other mutations are processed without an OCC check.

### 2.7. The Validation Pipeline and Check Ordering

Every request is evaluated against a fixed pipeline of check categories, in the order below, and the first category that fails determines the rejection. The ordering is load-bearing: an authentication failure masks everything downstream; a stale-version rejection surfaces before any state-machine precondition is examined; a segregation-of-duties violation is reported only after every other check has passed.

1. **Authentication context.** `X-User-ID` and `X-User-Role` are present and the role is a declared role — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization.** The role appears in the endpoint's authorized list — otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). Applies to all endpoints.
3. **Ownership.** An entity-backed actor matches the resource owner — a handler owns the animal, team, or visit's team; an evaluator is the assigned evaluator; a facility coordinator owns the facility of the target resource — otherwise `ERR_OWNERSHIP_MISMATCH` (HTTP 403). Applies to every endpoint acting on owned resources.
4. **Path existence, left to right.** Each resource identifier in the path is resolved in left-to-right order, and the first missing one rejects the request with HTTP 404 and the corresponding identifier: `ERR_HANDLER_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_EVALUATOR_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_VACCINATION_RECORD_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_ORIENTATION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, or `ERR_HOUR_CREDIT_NOT_FOUND`.
5. **Request-body schema.** Required fields are present, types match, enum values are within their declared sets (otherwise `ERR_INVALID_ENUM_VALUE`), unknown fields are rejected, minimum string lengths hold (an incident `description` runs at least ten characters), and date sanity holds — a start strictly before its end, `effective_from` on or before `effective_until`, `signed_on` not in the future, `approved_minutes` between zero and the scheduled minutes. Violations surface as `ERR_INVALID_REQUEST` (HTTP 400). Applies to all mutation endpoints.
6. **Stale-version concurrency.** The OCC rules of §2.6 — a mismatched expected version yields `ERR_STALE_VERSION` (HTTP 412). Applies only to the two endpoints named there.
7. **State preconditions.** The target resource's current state must permit the transition, per the state rules scattered through §3 — the family of `ERR_*_NOT_*` errors (HTTP 409). For visit scheduling this category covers the team being `ACTIVE` (`ERR_TEAM_NOT_ACTIVE`), the facility being `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), and the animal being `ACTIVE` (`ERR_ANIMAL_NOT_ACTIVE`); for requesting an evaluation it covers the handler being `ACTIVE` (`ERR_HANDLER_NOT_ACTIVE`) and the team being `FORMING` (`ERR_TEAM_NOT_FORMING`); for issuing a certification it covers the team being `FORMING` (`ERR_TEAM_NOT_FORMING`), the referenced evaluation being `PASSED` (`ERR_EVALUATION_NOT_PASSED`), and that evaluation belonging to the same team (`ERR_EVALUATION_TEAM_MISMATCH`).
8. **Animal welfare and biosafety.** The animal is not in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`), its rest block is satisfied (`ERR_ANIMAL_REST_PERIOD`), the forward workload ceiling holds (`ERR_WORKLOAD_LIMIT_EXCEEDED`), the daily visit limit holds (`ERR_DAILY_VISIT_LIMIT_EXCEEDED`), the species is admitted at the facility (`ERR_SPECIES_NOT_PERMITTED`), and a valid rabies vaccination covers the relevant date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`) — all HTTP 403. Applies to visit scheduling, offer acceptance, certification activation, renewal, and reinstatement, and to visit check-in (hold check only).
9. **Cross-entity referential integrity.** The team's certification is `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`), an `ACTIVE` agreement covers the facility and the scheduled date (`ERR_NO_ACTIVE_AGREEMENT`), orientation is `COMPLETED` and unexpired (`ERR_ORIENTATION_NOT_COMPLETED`), and a `SIGNED` waiver matches the facility's `required_waiver_version` (`ERR_WAIVER_NOT_ON_FILE`) — all HTTP 409. Applies to visit scheduling, offer acceptance, visit check-in (certification only), and facility reinstatement (agreement only).
10. **Temporal windows.** The family's window rules (HTTP 409): `ERR_VISIT_IN_PAST`, `ERR_TEAM_SCHEDULING_CONFLICT`, `ERR_EVALUATOR_SCHEDULING_CONFLICT`, `ERR_EVALUATION_SCHEDULE_IN_PAST`, `ERR_CHECKIN_TOO_EARLY`, `ERR_CHECKIN_WINDOW_PASSED`, `ERR_OFFER_EXPIRED`, `ERR_EVALUATION_APPEAL_WINDOW_CLOSED`, and `ERR_RENEWAL_WINDOW_CLOSED`. Applies to visit scheduling and the scheduling, scoring, check-in, acceptance, appeal, and renewal operations.
11. **Fiscal adequacy.** An `ACTIVE` insurance policy covering today exists (`ERR_NO_ACTIVE_INSURANCE`) and its coverage meets the applicable requirement (`ERR_INSURANCE_COVERAGE_INADEQUATE`) — both HTTP 402. Applies to visit scheduling, offer acceptance, certification activation, renewal, and reinstatement, and candidate-team eligibility.
12. **Capacity, uniqueness, and minimums** (HTTP 422): `ERR_VISIT_DURATION_EXCEEDS_CAP`, `ERR_FACILITY_CAPACITY_EXCEEDED`, `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`, `ERR_EVALUATOR_DAILY_CAP_EXCEEDED`, `ERR_ACTIVE_CERTIFICATION_EXISTS`, `ERR_ACTIVE_POLICY_EXISTS`, `ERR_WAIVER_ALREADY_EXISTS`, `ERR_ACTIVE_TEAM_EXISTS`, `ERR_ACTIVE_AGREEMENT_EXISTS`, `ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`, `ERR_TEAM_NOT_ELIGIBLE`, and `ERR_INVALID_ADJUSTMENT`. Applies to the creation and gate endpoints enumerated in §3.
13. **Segregation of duties.** On incident resolution only, the resolver must differ from the triager — otherwise `ERR_SOD_VIOLATION` (HTTP 403).

### 2.8. Bubble-Up and Cascade-Down Consistency

State propagates through the aggregate in two directions, and the server performs these reconciliations automatically whenever the criteria are met, without an explicit client request on the affected resource. Bubble-up lifts a parent or container when a child reaches a qualifying state: a certification's activation lifts its team from `FORMING` to `ACTIVE` and the animal from `REGISTERED` to `ACTIVE`; certification suspension and reinstatement lower and restore the team's status in step; a request-backed visit completing lifts its visit request from `ACCEPTED` to `FULFILLED`; drafting a facility's first agreement lifts the facility from `PROSPECT` to `ONBOARDING`, and an agreement reaching `ACTIVE` lifts the facility from `ONBOARDING` to `ACTIVE`.

Cascade-down resolves dependents when a governing resource fails: handler retirement, certification suspension or revocation, agreement loss, facility termination, insurance-lapse, and incident escalation each cancel standing `SCHEDULED` visits with a cause-specific `cancel_reason`, decrement the animal's `forward_workload_minutes` by each cancelled visit's scheduled minutes, and return request-backed visits' requests to `OPEN` with their offer fields cleared. Every resource mutated along either propagation direction has its `updated_at` refreshed and its `version` incremented.

### 2.9. The Volunteer Hour Ledger

Volunteer time is accounted in an append-only ledger of hour-credit rows rather than by overwriting balances. Each row records its `kind` — `PROVISIONAL`, `FINAL`, `REVERSAL`, or `ADJUSTMENT` — and a signed `minutes` amount: provisional and final rows are positive, reversal rows negative, and adjustment rows may carry either sign. A completed visit first earns an optimistic `PROVISIONAL` credit; verification replaces it by posting a `REVERSAL` row that exactly negates the provisional amount followed by the definitive `FINAL` row, so the net effect of the full cycle on the handler's lifetime total equals the final amount. Rounding order is pinned: each `FINAL` credit is rounded to whole fifteen-minute units at posting time, and the lifetime total then sums the already-rounded entries; summing raw durations and rounding once at the end is not the same calculation and is not used. The handler's `lifetime_minutes` is the algebraic sum over all of the handler's ledger rows, floored at zero — a posting that would drive the total below zero is rejected with `ERR_INVALID_ADJUSTMENT`.

### 2.10. Units, Precision, and Rounding

Durations are integer minutes; money amounts are integer cents. Where a computed quantity is a score or a displayed hour figure — the evaluation `composite_score`, a team's match score, a handler's `lifetime_hours` — it is rounded half-up to exactly two decimal places. The final visit credit is rounded half-up to the nearest whole fifteen-minute unit. Whole-quantity extractions floor toward zero: a visit's `actual_minutes` is the elapsed seconds between check-in and check-out divided by sixty and floored to whole minutes; late-cancel notice, volunteer tenure years, recency weeks, and workload-penalty ten-minute blocks all floor to whole units before thresholds apply. Calendar fields such as `activated_on`, `expires_on`, `valid_until`, `signed_on`, and `attended_on` are ISO calendar dates, while instants such as `scheduled_start`, `offered_at`, and `verified_at` are ISO 8601 UTC datetimes with three fractional digits. Where a boundary is inclusive or exclusive, the governing subsection says so explicitly; comparisons stated as "at least", "no more than", or "exactly … passes" are inclusive.

## 3. Business Logic & Workflows

### 3.1. Handlers, Animals, and Teams

A volunteer joins by self-registering — the one operation open to an `Anonymous` caller — supplying a legal `full_name`, a contact `email` that must be unique across handlers, a free-form two-letter home `region_code`, and the `volunteer_since` date marking when the volunteer first joined any program (this date later drives the experience component of match scoring); a `phone` number is optional. A new handler starts in `APPLICANT` status with `lifetime_minutes` at zero and `recognition_tier` `NONE`. A `ProgramAdmin` reviews the application: approval moves the handler `APPLICANT → ACTIVE`, and rejection — a call that carries a `reason` — moves it to the terminal `REJECTED` state; either action on a handler no longer in `APPLICANT` fails with `ERR_HANDLER_NOT_APPLICANT`. The handler list accepts optional `status` and `recognition_tier` filters.

Compliance discipline on handlers is deliberately non-cascading. A `ComplianceOfficer` may suspend an `ACTIVE` handler — the suspension call carries a `reason` that is recorded in the handler's `suspension_reason` — and any other starting state fails with `ERR_HANDLER_NOT_ACTIVE`. Handler suspension does not touch the handler's existing `SCHEDULED` visits or certifications; it simply marks the person. Reinstatement by a `ComplianceOfficer` requires `SUSPENDED` (otherwise `ERR_HANDLER_NOT_SUSPENDED`) and clears `suspension_reason`.

Retirement, by contrast, cascades hard. A handler may retire themself, or a `ProgramAdmin` may retire them, from `ACTIVE` or `SUSPENDED` — any other state fails with `ERR_HANDLER_NOT_ACTIVE`. Retirement is terminal (`RETIRED`) and tears down the operation: every team of the handler in `FORMING`, `ACTIVE`, or `SUSPENDED` moves to `DISSOLVED`; every visit of those teams still `SCHEDULED` is cancelled with `cancel_reason` `TEAM_DISSOLVED`; each cancelled visit decrements its animal's `forward_workload_minutes`; and any request-backed visit returns its visit request to `OPEN` with offer fields cleared.

Once approved, a handler registers animals. Registration supplies the animal's `name`, `species` (one of `DOG`, `CAT`, `RABBIT`, `GUINEA_PIG`, `BIRD`, `MINIATURE_HORSE`), `breed`, and `date_of_birth`; the server stamps the owning `handler_id` from the caller's `X-User-ID`, and the animal starts `REGISTERED`. An animal bubbles up to `ACTIVE` automatically when a team containing it has its certification activated, and compliance action can move it into and out of `WELFARE_HOLD` (§3.9). The animal record also exposes three computed fields: `welfare_blocked_until`, the rest-block expiry owed from the most recent completed visit and null when no rest is owed; `forward_workload_minutes`, the forward-looking workload figure; and `audit_workload_minutes`, the audit-window figure — both workload variants defined in §3.7. A handler retires an owned animal from `REGISTERED` or `ACTIVE` (otherwise `ERR_ANIMAL_NOT_RETIRABLE`), but only while no team containing the animal stands in `FORMING`, `ACTIVE`, or `SUSPENDED` — a live team blocks retirement with `ERR_ANIMAL_HAS_ACTIVE_TEAM`. The animal list accepts `handler_id`, `status`, and `species` filters.

A team pairs one of the handler's animals with the handler under a display `team_name`, formed by a payload carrying the `animal_id`; the animal must belong to the creating handler, and an animal may belong to at most one team not yet `DISSOLVED` — a second formation attempt fails with `ERR_ACTIVE_TEAM_EXISTS`. A new team starts `FORMING` and thereafter mirrors its certification: it bubbles up `FORMING → ACTIVE` when the certification first activates, drops `ACTIVE → SUSPENDED` whenever the certification is suspended, and returns `SUSPENDED → ACTIVE` on reinstatement. Three penalty counters — `late_cancel_count`, `no_show_count`, and `warning_count` — all start at zero and accrue per §3.7 and §3.9. A handler may dissolve a team from `FORMING`, `ACTIVE`, or `SUSPENDED`, but only while no visit of the team stands in `SCHEDULED` or `IN_PROGRESS` (otherwise `ERR_TEAM_HAS_SCHEDULED_VISITS`) and no certification of the team stands in `PROVISIONAL`, `ACTIVE`, `RENEWAL_DUE`, or `SUSPENDED` (otherwise `ERR_TEAM_HAS_ACTIVE_CERTIFICATION`) — the certification must be revoked or absent first. System-driven dissolutions are the exception: the handler-retirement cascade above, and the incident-`REVOCATION` resolution of §3.9 which revokes the team's certification as part of the same cascade, dissolve teams without those gates. The team list accepts `handler_id`, `animal_id`, and `status` filters.

### 3.2. Evaluations and Temperament Scoring

Evaluators are the program's certified scorers. A `ProgramAdmin` creates an evaluator with `full_name`, `email`, operating `region_code`, a non-empty `specializations` list naming the species the evaluator is certified to score, and optionally a `max_evaluations_per_day` cap — an integer from one to eight that defaults to four when omitted. An evaluator starts `ACTIVE`. A `ProgramAdmin` may later patch the evaluator's `status`, `specializations`, or `max_evaluations_per_day`; moving an evaluator to `INACTIVE` blocks all new scheduling to that evaluator (`ERR_EVALUATOR_NOT_ACTIVE`) while leaving existing `SCHEDULED` evaluations fully scorable, and moving back to `ACTIVE` restores scheduling. The evaluator list accepts `status` and `region_code` filters.

A handler initiates the certification pipeline by requesting an evaluation for a team — the payload carries the `team_id` — provided the handler is `ACTIVE` (otherwise `ERR_HANDLER_NOT_ACTIVE`) and the team is still `FORMING` (otherwise `ERR_TEAM_NOT_FORMING`). The new evaluation starts `REQUESTED` with `requested_at` stamped at creation, `attempt_number` at one, and `evaluator_id`, `scheduled_start`, `scheduled_end`, and both score fields unset. The evaluation list accepts `team_id`, `evaluator_id`, and `status` filters.

Scheduling is performed by a `ProgramAdmin`, who supplies the `evaluator_id`, `scheduled_start`, and `scheduled_end`. The evaluation must stand in `REQUESTED` or `APPEALED` (otherwise `ERR_EVALUATION_NOT_SCHEDULABLE`); the evaluator must be `ACTIVE` (`ERR_EVALUATOR_NOT_ACTIVE`); the team's animal species must appear in the evaluator's `specializations` (`ERR_EVALUATOR_SPECIES_MISMATCH`); the `scheduled_start` must not lie in the past (`ERR_EVALUATION_SCHEDULE_IN_PAST`); and the session must run between thirty and one hundred twenty minutes inclusive (`ERR_EVALUATION_DURATION_INVALID`). Two capacity rules protect the evaluator's calendar. First, a conflict rule with a thirty-minute hygiene buffer: the new evaluation's raw interval — start inclusive, end exclusive — may not intersect the buffered interval of any other `SCHEDULED` evaluation of the same evaluator, where each existing evaluation is padded by thirty minutes on both sides; equivalently the gap between back-to-back sessions must be at least thirty minutes, so bare adjacency conflicts while a gap of exactly thirty minutes passes (`ERR_EVALUATOR_SCHEDULING_CONFLICT`). Second, a daily cap: the evaluator must have fewer than `max_evaluations_per_day` `SCHEDULED` evaluations on that UTC calendar day (`ERR_EVALUATOR_DAILY_CAP_EXCEEDED`). Successful scheduling sets `evaluator_id`, `scheduled_start`, and `scheduled_end`, moves the evaluation to `SCHEDULED`, and — when the evaluation was re-scheduled out of `APPEALED` — increments `attempt_number` by one.

Scoring belongs to the assigned `Evaluator` and only after the session has concluded: the evaluation must be `SCHEDULED` (otherwise `ERR_EVALUATION_NOT_SCHEDULED`), the acting evaluator must be the one named in `evaluator_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and the current time must be at or past `scheduled_end` (otherwise `ERR_EVALUATION_NOT_CONCLUDED`). The scorer submits an `aptitude_score` and an `obedience_score`, each an integer from zero to one hundred. The `composite_score` is sixty percent of the aptitude score plus forty percent of the obedience score, rounded half-up to two decimal places. The pass rule depends on the attempt: on a first attempt the team passes when both section scores are at least seventy and the composite is at least 75.0; on a retake — `attempt_number` two or higher — the bar rises to a composite of at least 80.0 alongside the same section floors. A passing result routes the evaluation to the terminal `PASSED` state; anything short routes it to `FAILED` and stamps `failed_at`. Either way `aptitude_score`, `obedience_score`, `composite_score`, and `scored_at` are recorded.

A failed team is not finished. The handler may appeal within fourteen days of `failed_at`: appealing a non-`FAILED` evaluation fails with `ERR_EVALUATION_NOT_FAILED`, and appealing after the fourteenth day fails with `ERR_EVALUATION_APPEAL_WINDOW_CLOSED`; a timely appeal moves the evaluation `FAILED → APPEALED`, from which a `ProgramAdmin` schedules the retake under the ordinary scheduling rules. Cancellation, available to the handler or a `ProgramAdmin` from `REQUESTED`, `SCHEDULED`, or `APPEALED` (otherwise `ERR_EVALUATION_NOT_CANCELLABLE`), moves the evaluation to the terminal `CANCELLED` state. Two sweeps keep the pipeline clean: a `REQUESTED` evaluation left unscheduled for more than sixty days after `requested_at` expires, and a `FAILED` evaluation whose appeal window lapses — more than fourteen days past `failed_at` — likewise moves to `EXPIRED`.

### 3.3. Certification Issuance, Renewal, and Discipline

Certification begins with health records. A handler records each vaccination for an owned animal by supplying the `animal_id`, the `vaccine_type` (one of `RABIES`, `DISTEMPER`, `BORDETELLA`, `CANINE_INFLUENZA`, `FELINE_FVRCP`), the `administered_on` date, the `valid_until` date, the administering `veterinarian_name`, and optionally the `clinic_name`; the record starts `VALID` and remains valid while today is on or before `valid_until`. A sweep moves a record `VALID → EXPIRED` once today passes `valid_until`; expiry is deliberately passive — it does not touch any certification, it simply fails future gates. A `ComplianceOfficer` may void a `VALID` record (otherwise `ERR_VACCINATION_NOT_VALID`) — a call that carries a `reason` — moving it to the terminal `VOIDED` state. The rabies gate used throughout this document asks for a `RABIES` record in `VALID` status whose `valid_until` covers the relevant date: when no rabies record exists for the animal at all, the rejection is `ERR_VACCINATION_MISSING`; when records exist but none covers the date — including a record whose validity has lapsed whether or not the sweep has yet marked it `EXPIRED` — the rejection is `ERR_VACCINATION_EXPIRED`. The vaccination list accepts `animal_id`, `status`, and `vaccine_type` filters.

Issuance turns a passed evaluation into a credential. A `ProgramAdmin` issues a certification with a payload naming the `team_id` and the `evaluation_id`; the team must be `FORMING` (`ERR_TEAM_NOT_FORMING`), the referenced evaluation must be `PASSED` (`ERR_EVALUATION_NOT_PASSED`) and must belong to that same team (`ERR_EVALUATION_TEAM_MISMATCH`), and the team must not already hold a certification in `PROVISIONAL`, `ACTIVE`, `RENEWAL_DUE`, or `SUSPENDED` (`ERR_ACTIVE_CERTIFICATION_EXISTS`). The new certification starts `PROVISIONAL`. The certification list accepts `team_id`, `evaluation_id`, and `status` filters.

Activation is the go-live gate, performed by a `ProgramAdmin` on a `PROVISIONAL` certification (otherwise `ERR_CERT_NOT_PROVISIONAL`). Two gates must pass: the animal must hold a valid rabies vaccination covering today (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`), and the handler must hold an `ACTIVE` insurance policy whose effective window covers today with `coverage_cents` of at least one hundred million cents — one million dollars (`ERR_NO_ACTIVE_INSURANCE` when no active policy covers today, `ERR_INSURANCE_COVERAGE_INADEQUATE` when one exists but falls short). Activation stamps `activated_on` with today and `expires_on` with today plus seven hundred thirty days, and bubbles the team `FORMING → ACTIVE` and the animal `REGISTERED → ACTIVE`.

Renewal runs on a fixed calendar. A sweep moves an `ACTIVE` certification to `RENEWAL_DUE` once today enters the window from sixty days before `expires_on` through `expires_on` itself; once today passes `expires_on`, both `ACTIVE` and `RENEWAL_DUE` certifications move to `EXPIRED`. A `ProgramAdmin` renews from `RENEWAL_DUE` or `EXPIRED` (otherwise `ERR_CERT_NOT_RENEWABLE`), but a lapsed certification may only be renewed while today is within ninety days past `expires_on` inclusive — beyond that the window is closed (`ERR_RENEWAL_WINDOW_CLOSED`). Renewal re-checks the rabies gate and the program insurance floor of one hundred million cents, and it enforces an experience requirement: the team must have at least six visits in `COMPLETED` with `VERIFIED` verification whose `actual_end` dates fall within the span from `activated_on` through the pre-renewal `expires_on` (`ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`). The computation order is pinned to break the apparent circularity: first the eligibility visits are counted against the old expiry date; then the new `expires_on` is set to the later of today and the old expiry, plus seven hundred thirty days — an on-time renewal therefore extends from the old expiry and loses no days, while a late renewal extends from today; finally `renewal_count` increments by one.

Suspension is the workhorse of enforcement. A `ComplianceOfficer` may suspend from `ACTIVE` or `RENEWAL_DUE` (otherwise `ERR_CERT_NOT_SUSPENDABLE`); the manual call carries a `reason` and may optionally set `suspension_until`. The same transition fires automatically on incident precaution, insurance lapse, and the late-cancel threshold (§3.7). The recorded `suspension_reason` is one of `MANUAL`, `INCIDENT_PRECAUTION`, `INCIDENT_SUSPENSION`, `INSURANCE_LAPSE`, or `LATE_CANCELLATIONS`, and `suspension_until` is set only for `INCIDENT_SUSPENSION`. Suspension cascades immediately: the team drops `ACTIVE → SUSPENDED`; every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `CERT_SUSPENDED`; each cancelled visit decrements the animal's `forward_workload_minutes`; and request-backed cancelled visits return their visit requests to `OPEN` with offer fields cleared.

Reinstatement re-gates rather than rubber-stamps. A `ComplianceOfficer` reinstates a `SUSPENDED` certification (otherwise `ERR_CERT_NOT_SUSPENDED`) only once `suspension_until` is null or has been reached (a future `suspension_until` fails with `ERR_SUSPENSION_NOT_ELAPSED`), and only after re-passing the rabies gate (`ERR_VACCINATION_EXPIRED`) and the insurance floor (`ERR_INSURANCE_COVERAGE_INADEQUATE`) against today. Reinstatement clears `suspension_reason` and `suspension_until` and bubbles the team `SUSPENDED → ACTIVE`; `expires_on` is unchanged — a suspension never extends the certification term.

Revocation is terminal. A `ComplianceOfficer` revokes from `ACTIVE`, `RENEWAL_DUE`, or `SUSPENDED` (otherwise `ERR_CERT_NOT_REVOKABLE`) with a `reason`, and an incident resolved as `REVOCATION` revokes automatically (§3.9). Revocation dissolves the team, cancels every remaining `SCHEDULED` visit with `cancel_reason` `CERT_REVOKED`, and returns request-backed visits' requests to `OPEN`.

### 3.4. Facilities, Partnership Agreements, Orientation, and Waivers

A `ProgramAdmin` registers a facility with its `name`, `facility_type` (`HOSPITAL`, `SCHOOL`, `NURSING_HOME`, `REHAB_CENTER`, or `HOSPICE`), `region_code`, and optionally a street `address`, together with the four operating rules that govern every future visit: `max_visit_minutes` capping a single visit's scheduled duration, a non-empty `allowed_species` list, `min_liability_coverage_cents` setting the facility's insurance floor, `max_overlapping_teams` capping how many visits may overlap at any instant, and `visits_per_week_cap` capping weekly volume; `required_waiver_version` names the waiver text the facility requires and defaults to `"v1"`. A new facility starts `PROSPECT`. A `ProgramAdmin` may patch the rule set — `name`, `max_visit_minutes`, `allowed_species`, `min_liability_coverage_cents`, `max_overlapping_teams`, `visits_per_week_cap`, `required_waiver_version` — and changes apply prospectively to new visits only; existing visits are unchanged. The facility list accepts `status`, `facility_type`, and `region_code` filters.

The facility lifecycle is contract-driven. Drafting the facility's first agreement bubbles it `PROSPECT → ONBOARDING`; an agreement reaching `ACTIVE` bubbles it `ONBOARDING → ACTIVE` — though a facility under suspension stays `SUSPENDED` until reinstated. A `ComplianceOfficer` may suspend an `ACTIVE` facility (otherwise `ERR_FACILITY_NOT_ACTIVE`) with a `reason`; a manual suspension keeps every existing `SCHEDULED` visit in place but blocks all new scheduling. Reinstatement by a `ComplianceOfficer` requires `SUSPENDED` (otherwise `ERR_FACILITY_NOT_SUSPENDED`) and, critically, an `ACTIVE` agreement already in place (otherwise `ERR_NO_ACTIVE_AGREEMENT`). A `ProgramAdmin` may terminate a facility from any non-terminal state — `ACTIVE`, `SUSPENDED`, `ONBOARDING`, or `PROSPECT` (a repeat termination fails with `ERR_FACILITY_ALREADY_TERMINAL`) — with a `reason`, moving the facility to the terminal `TERMINATED` state; termination from `ACTIVE` or `SUSPENDED` moves the facility's `ACTIVE` agreement to `TERMINATED` and runs the full agreement-loss cascade described below, while terminating an `ONBOARDING` or `PROSPECT` facility performs no cascade.

The partnership agreement is a two-signature handshake. A `ProgramAdmin` drafts it with the `facility_id`, the coverage span `start_on` through `end_on` — the start strictly before the end, both inclusive as coverage dates — the contract caps `agreed_max_visit_minutes` and `insurance_minimum_cents`, and a `terms_version` label; a facility may carry only one agreement in `DRAFT`, `PENDING_FACILITY_SIGNATURE`, `PENDING_PROGRAM_SIGNATURE`, or `ACTIVE` at a time (a second fails with `ERR_ACTIVE_AGREEMENT_EXISTS`). Submitting moves the draft `DRAFT → PENDING_FACILITY_SIGNATURE` (otherwise `ERR_AGREEMENT_NOT_DRAFT`). The facility's coordinator countersigns — the acting coordinator's facility must be the agreement's `facility_id` (`ERR_OWNERSHIP_MISMATCH`), the agreement must await the facility signature (`ERR_AGREEMENT_NOT_AWAITING_FACILITY`), and today must not be past `end_on` (`ERR_AGREEMENT_TERM_PASSED`) — moving it to `PENDING_PROGRAM_SIGNATURE`. The program's countersignature by a `ProgramAdmin` (awaiting program signature, otherwise `ERR_AGREEMENT_NOT_AWAITING_PROGRAM`; term likewise unexpired, otherwise `ERR_AGREEMENT_TERM_PASSED`) activates the agreement and bubbles the facility `ONBOARDING → ACTIVE`. A `ProgramAdmin` may withdraw the agreement from any of the three pre-activation states into `WITHDRAWN`; withdrawing from any other state fails with `ERR_AGREEMENT_NOT_WITHDRAWABLE`.

Agreement loss is a full teardown. Terminating an `ACTIVE` agreement — available to a `ProgramAdmin` or to the facility's own coordinator, otherwise `ERR_AGREEMENT_NOT_ACTIVE` or `ERR_OWNERSHIP_MISMATCH` — moves the agreement to `TERMINATED`, records the supplied `reason` in `terminated_reason`, and cascades: the facility drops `ACTIVE → SUSPENDED`; every `SCHEDULED` visit at the facility is cancelled with `cancel_reason` `AGREEMENT_ENDED` and the animals' `forward_workload_minutes` decremented; request-backed cancelled visits return their requests to `OPEN`; and every visit request of the facility still `OPEN` or `OFFERED` moves to `WITHDRAWN`. The same cascade fires when a sweep expires an `ACTIVE` agreement once today passes `end_on`. The agreement list accepts `facility_id` and `status` filters.

Orientation ties a team to a facility before the first visit. A facility coordinator assigns a team by its `team_id`; the record's `facility_id` is derived from the coordinator's own `X-User-ID`, and the record starts `ASSIGNED`. Completion — by a coordinator of the same facility (`ERR_OWNERSHIP_MISMATCH`) on an `ASSIGNED` record (otherwise `ERR_ORIENTATION_NOT_ASSIGNED`) — records the `attended_on` date, which may not lie in the future (`ERR_ORIENTATION_DATE_FUTURE`), and sets `expires_on` to `attended_on` plus three hundred sixty-five days. A sweep expires a `COMPLETED` record once today passes `expires_on`, and a coordinator may re-assign an `EXPIRED` record (otherwise `ERR_ORIENTATION_NOT_EXPIRED`), which clears `attended_on` and `expires_on` and returns it to `ASSIGNED` — the cycle begins again. The orientation list accepts `team_id`, `facility_id`, and `status` filters.

The liability waiver is the team's signature on the facility's terms. A handler signs one for an owned team by supplying the `team_id`, `facility_id`, `waiver_version`, and `signed_on` date; the record starts `SIGNED`, and only one `SIGNED` waiver may exist for a given team–facility–version triple (a duplicate fails with `ERR_WAIVER_ALREADY_EXISTS`). A waiver authorizes visits only while `SIGNED` and only while its `waiver_version` equals the facility's current `required_waiver_version`; visit creation without a matching waiver fails with `ERR_WAIVER_NOT_ON_FILE`. A `ComplianceOfficer` may void a `SIGNED` waiver (otherwise `ERR_WAIVER_NOT_SIGNED`) with a `reason`, moving it to `VOIDED`; voiding is purely prospective — existing `SCHEDULED` visits are unaffected. The waiver list accepts `team_id`, `facility_id`, and `status` filters.

### 3.5. Insurance Policies and Coverage Adequacy

A handler registers each liability policy with the `insurer_name`, a `policy_number` unique per handler, the `coverage_cents` amount, and the inclusive coverage window `effective_from` through `effective_until` (the end may not precede the start); the owning `handler_id` comes from the caller's identity and the policy starts `PENDING`. Verification by a `ProgramAdmin` requires `PENDING` (otherwise `ERR_POLICY_NOT_PENDING`), requires today to fall within the effective window inclusive (otherwise `ERR_POLICY_WINDOW_INVALID`), and enforces one active policy per handler — verifying a second while another stands `ACTIVE` fails with `ERR_ACTIVE_POLICY_EXISTS`. A sweep expires an `ACTIVE` policy once today passes `effective_until`; expiry is deliberately silent — unlike cancellation it suspends nothing, and future gates simply fail for want of an active policy. The policy list accepts `handler_id` and `status` filters.

Cancellation, available to the owning handler or a `ProgramAdmin` from `PENDING` or `ACTIVE` (otherwise `ERR_POLICY_NOT_CANCELLABLE`), is where the teeth are. Cancelling a `PENDING` policy is inert. Cancelling an `ACTIVE` policy runs the insurance-lapse cascade in four hops: first, every certification of the handler's teams standing in `ACTIVE` or `RENEWAL_DUE` is examined, and if no remaining `ACTIVE` policy covers today with at least one hundred million cents of coverage, that certification moves to `SUSPENDED` with `suspension_reason` `INSURANCE_LAPSE`; second, each freshly suspended certification's team drops to `SUSPENDED`; third, every `SCHEDULED` visit of each such team is cancelled with `cancel_reason` `CERT_SUSPENDED` and the animal's `forward_workload_minutes` decremented per visit; fourth, request-backed cancelled visits return their visit requests to `OPEN` with offer fields cleared.

Adequacy is judged against the operation at hand. Certification-level operations — activation, renewal, and reinstatement — apply the program floor: one hundred million cents. Visit-level operations — direct scheduling, offer acceptance, and candidate-team eligibility — apply the facility-specific requirement: the base is the greater of one hundred million cents and the facility's `min_liability_coverage_cents`, and for a `HOSPITAL` that base is multiplied by one and a half, rounded half-up to a whole cent. Coverage is adequate when an `ACTIVE` policy of the team's handler exists whose effective window covers today and whose `coverage_cents` is at least the requirement — equality passes. When no `ACTIVE` policy covers today the rejection is `ERR_NO_ACTIVE_INSURANCE`; when one exists but falls short it is `ERR_INSURANCE_COVERAGE_INADEQUATE`.

### 3.6. Visit Requests and Candidate Matching

A facility coordinator posts a visit request for their own facility — the `facility_id` is derived from the coordinator's identity — with a `requested_start` that must lie in the future (`ERR_VISIT_IN_PAST`), a `requested_end` bounding the session to between thirty and one hundred twenty minutes (a shorter session fails `ERR_VISIT_DURATION_INVALID`; a longer one exceeds the flat program ceiling and fails `ERR_VISIT_DURATION_EXCEEDS_CAP`), an optional `species_preference` drawn from the same species enum as animals (omitting it means the request is open to any species), a `visit_program` of `READING`, `REHAB`, `STRESS_RELIEF`, or `GENERAL`, and a `priority` of `ROUTINE`, `HIGH`, or `URGENT` that later feeds the match-score multiplier. The request starts `OPEN` with `decline_count` at zero. The request list accepts `facility_id`, `status`, `priority`, and `offered_team_id` filters.

The candidate-teams capability hands a `ProgramAdmin` a ranked slate for an open request. A team is eligible only when every one of the following holds: the team is `ACTIVE`; its handler is `ACTIVE`; its animal is `ACTIVE` with no welfare hold in force (`welfare_hold_until` null); the team's certification is `ACTIVE`; a `SIGNED` waiver exists for the team and the request's facility whose `waiver_version` equals the facility's `required_waiver_version`; an orientation record for the team at that facility stands `COMPLETED` with `expires_on` today or later; the handler's insurance is adequate per the facility-specific requirement of §3.5; and, for a `NURSING_HOME`, the handler's `recognition_tier` is anything other than `NONE`. Each surviving team is scored. Experience contributes five points per full year elapsed since the handler's `volunteer_since`, capped at forty points. Species contributes twenty-five points when the animal's `species` equals the request's `species_preference`, ten points when the request names no preference, and zero on a mismatch. Recency contributes twenty points minus two per full week since the team's most recent `VERIFIED` visit to that facility, clamped between zero and twenty — and a team that has never had a verified visit there scores zero. The workload penalty subtracts one point per full ten minutes of the animal's current `forward_workload_minutes`, capped at thirty. The subtotal — experience plus species plus recency minus penalty — is then multiplied by 1.5 for an `URGENT` request, 1.2 for `HIGH`, or 1.0 for `ROUTINE`, and the product rounded half-up to two decimal places is the team's score. The slate is ranked by score descending with ties broken by the team's `created_at` ascending; an empty candidate pool is not an error — the response is an empty array with HTTP 200.

Offering is the matchmaker's act. A `ProgramAdmin` offers an `OPEN` request (otherwise `ERR_REQUEST_NOT_OPEN`) to a chosen team by submitting the `team_id` together with the OCC field `expected_visit_request_version` per §2.6 — a stale view of the request fails with `ERR_STALE_VERSION` — and the named team must pass the full eligibility filter above (otherwise `ERR_TEAM_NOT_ELIGIBLE`). A successful offer stamps `offered_team_id`, sets `offered_at` to now, fixes `offer_expires_at` seventy-two hours later, moves the request to `OFFERED`, and increments the request's `version` by one.

The offered team's handler then decides. Acceptance requires the request still `OFFERED` (otherwise `ERR_REQUEST_NOT_OFFERED`), the acting handler to own the offered team (otherwise `ERR_OWNERSHIP_MISMATCH`), and the clock not past `offer_expires_at` (otherwise `ERR_OFFER_EXPIRED`); it then re-runs the entire visit-creation gate chain of §3.7 against the requested window — safety, referential, temporal, fiscal, and constraint checks alike. Acceptance creates the visit with the offered `team_id`, the request's `facility_id`, the requested window as its `scheduled_start` and `scheduled_end`, and the `request_id` linking back to the request; the visit starts `SCHEDULED` and `UNVERIFIED`, the request moves to `ACCEPTED`, the team's `version` increments by one, and the animal's `forward_workload_minutes` rises by the scheduled minutes per the forward-looking variant. Declining — again the offered team's handler, same `OFFERED` and ownership gates — returns the request to `OPEN`, clears `offered_team_id`, `offered_at`, and `offer_expires_at`, and increments `decline_count`; when instead the seventy-two hours lapse, the sweep performs the same return to `OPEN` and clearing but does not increment `decline_count`. The coordinator who owns the facility may withdraw the request from `OPEN` or `OFFERED` into `WITHDRAWN` — any other state fails with `ERR_REQUEST_NOT_WITHDRAWABLE` — which is also where the agreement-loss cascade sweeps the facility's outstanding requests.

Requests resolve in four terminal directions. Completion of the backed visit bubbles the request `ACCEPTED → FULFILLED` and stamps `fulfilled_on` with the date. Cancellation or no-show of the backed visit compensates the request `ACCEPTED → OPEN`, clearing the offer fields while the visit keeps its `request_id` linkage. A request still `OPEN` once its `requested_end` has passed is swept to `EXPIRED` with `expired_on` stamped — the raw material of the unmet-demand measure of §3.8. And withdrawal ends the request at `WITHDRAWN`.

### 3.7. Scheduling and Conducting a Visit

Direct scheduling lets a `ProgramAdmin` book a team into a facility in one call carrying the `team_id`, `facility_id`, `scheduled_start`, `scheduled_end`, and the OCC field `expected_team_version`. The version check fires first per the pipeline — a mismatch with the team's current `version` is rejected with `ERR_STALE_VERSION` — and the full gate chain then runs in the pipeline's order. State: the team must be `ACTIVE` (`ERR_TEAM_NOT_ACTIVE`), the facility `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), the animal `ACTIVE` (`ERR_ANIMAL_NOT_ACTIVE`). Safety: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the animal's rest block must be satisfied — `scheduled_start` at or after `welfare_blocked_until`, with an earlier start failing `ERR_ANIMAL_REST_PERIOD`; the forward workload gate must hold — the animal's existing forward-looking workload plus the new visit's scheduled minutes may not exceed two hundred forty minutes, with a total of exactly two hundred forty allowed and anything beyond rejected `ERR_WORKLOAD_LIMIT_EXCEEDED`; the daily limit must hold — an animal already standing on two visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` on that UTC calendar day rejects a third with `ERR_DAILY_VISIT_LIMIT_EXCEEDED`; the animal's `species` must appear in the facility's `allowed_species` (`ERR_SPECIES_NOT_PERMITTED`); and a valid rabies vaccination must cover the scheduled date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`). Referential: the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); an `ACTIVE` agreement must cover the facility on the scheduled date (`ERR_NO_ACTIVE_AGREEMENT`); orientation for the team at this facility must be `COMPLETED` and unexpired (`ERR_ORIENTATION_NOT_COMPLETED`); and a `SIGNED` waiver matching the facility's `required_waiver_version` must be on file (`ERR_WAIVER_NOT_ON_FILE`). Temporal: `scheduled_start` must lie in the future (`ERR_VISIT_IN_PAST`), and the new interval — start inclusive, end exclusive — must not overlap any other `SCHEDULED` or `IN_PROGRESS` visit of the same team, with bare adjacency allowed (`ERR_TEAM_SCHEDULING_CONFLICT`). Fiscal: the facility-specific insurance adequacy of §3.5 (`ERR_NO_ACTIVE_INSURANCE` / `ERR_INSURANCE_COVERAGE_INADEQUATE`). Constraints: the scheduled duration must run at least thirty minutes (`ERR_VISIT_DURATION_INVALID`) and at most the effective cap — the smallest of the facility's `max_visit_minutes`, the covering agreement's `agreed_max_visit_minutes`, and the program ceiling of one hundred twenty minutes, with a duration exactly equal to the cap allowed and anything longer failing `ERR_VISIT_DURATION_EXCEEDS_CAP`; the resulting count of visits at the facility whose scheduled intervals overlap at any instant must not exceed `max_overlapping_teams` (`ERR_FACILITY_CAPACITY_EXCEEDED`); and the facility's count of visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` within the ISO week — Monday through Sunday — must stand below `visits_per_week_cap`, a booking made while the count already equals the cap failing `ERR_FACILITY_WEEKLY_CAP_EXCEEDED`. A visit that clears the chain starts `SCHEDULED` and `UNVERIFIED`, increments the team's `version` by one, and raises the animal's `forward_workload_minutes` by the scheduled minutes. The visit list accepts `team_id`, `facility_id`, `request_id`, `lifecycle_status`, and `verification_status` filters.

The two workload figures on the animal deserve a precise statement, because they answer different questions. The forward-looking figure `forward_workload_minutes` looks across the window from seven days before now to seven days after now — the future bound excluded — and counts the animal's teams' visits in `SCHEDULED` or `IN_PROGRESS` at their scheduled minutes plus visits in `COMPLETED` at their `actual_minutes`. The audit figure `audit_workload_minutes` looks across the window from seven days before now through now inclusive and counts only `COMPLETED` visits at their `actual_minutes`. Visits `CANCELLED` or `NO_SHOW` are excluded from both, and both figures are recomputed at booking, acceptance, check-out, cancellation, and no-show — so a heavily booked but untested animal shows a forward figure well above its audit figure.

Check-in belongs to the handler who owns the visit's team (otherwise `ERR_OWNERSHIP_MISMATCH`) and requires the visit still `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`). Three gates guard the moment: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); and the clock must sit within the check-in window — no earlier than fifteen minutes before `scheduled_start` (earlier fails `ERR_CHECKIN_TOO_EARLY`) and no later than `scheduled_end` (later fails `ERR_CHECKIN_WINDOW_PASSED`). Check-in stamps `actual_start` and moves the visit to `IN_PROGRESS`.

Check-out, likewise the owning handler's act on an `IN_PROGRESS` visit (otherwise `ERR_VISIT_NOT_IN_PROGRESS`), stamps `actual_end` and derives `actual_minutes` as the elapsed seconds between `actual_start` and `actual_end` divided by sixty, floored to whole minutes. It then posts the provisional hour credit — a `PROVISIONAL` row equal to the scheduled minutes regardless of how long the visit actually ran — and recomputes the handler's `lifetime_minutes` and `recognition_tier`. Animal welfare bookkeeping lands at the same moment: the visit's rest requirement is sixty minutes when the visit ran thirty minutes or less, one hundred twenty minutes when it ran thirty-one to sixty, and two hundred forty minutes when it ran sixty-one or more, and the animal's `welfare_blocked_until` is set to `actual_end` plus that rest requirement; both workload figures are recomputed. When the visit is request-backed, its request bubbles `ACCEPTED → FULFILLED` with `fulfilled_on` stamped. The visit closes at `COMPLETED`.

Cancellation is permitted from `SCHEDULED` only (otherwise `ERR_VISIT_NOT_CANCELLABLE`) and may be initiated by the owning handler, a `ProgramAdmin`, or the coordinator of the visit's facility (each with their ownership check). The cancellation stamps `cancelled_at` and records a `cancel_reason` mapped from the actor — `HANDLER_CANCEL`, `ADMIN_CANCEL`, or `FACILITY_CANCEL` — or from the system cause when a cascade drives it: `AGREEMENT_ENDED`, `CERT_SUSPENDED`, `CERT_REVOKED`, `TEAM_DISSOLVED`, or `INCIDENT_PRECAUTION`. The animal's `forward_workload_minutes` drops by the visit's scheduled minutes, compensating the scheduling increment, and a request-backed visit returns its request `ACCEPTED → OPEN` with offer fields cleared. Handler-initiated cancellation alone carries the late-cancel penalty, tiered by notice floored to whole hours before `scheduled_start`: forty-eight hours or more costs nothing; twenty-four up to forty-eight hours adds one point to the team's `late_cancel_count`; under twenty-four hours adds two. When the counter reaches three or more points, the team's certification standing `ACTIVE` or `RENEWAL_DUE` is suspended with `suspension_reason` `LATE_CANCELLATIONS` and no `suspension_until`, and the counter resets to zero.

The no-show sweep handles silent absences: a visit still `SCHEDULED` more than thirty minutes past its `scheduled_end` moves to `NO_SHOW`, the team's `no_show_count` increments by one, the animal's `forward_workload_minutes` drops by the scheduled minutes, and a request-backed visit's request returns `ACCEPTED → OPEN`.

### 3.8. Verification, Disputes, and Volunteer Recognition

A completed visit's hours are not final until the facility speaks. Verification status moves only while the visit stands `COMPLETED`, and starts at `UNVERIFIED`. The coordinator of the visit's facility verifies a completed visit (`ERR_VISIT_NOT_COMPLETED` otherwise) still `UNVERIFIED` (`ERR_VISIT_ALREADY_RESOLVED` otherwise), with the usual facility ownership check: `verified_at` is stamped, and the credit is reconciled in two postings — a `REVERSAL` row negating the provisional amount, then a `FINAL` row computed as the smallest of the visit's `actual_minutes`, its scheduled minutes, and the effective cap in minutes, divided by fifteen, rounded half-up to the nearest whole unit, and multiplied by fifteen. The handler's `lifetime_minutes` and `recognition_tier` are recomputed, and the visit stands `VERIFIED`.

When the facility disagrees with the record, the same coordinator instead disputes the completed, still-`UNVERIFIED` visit with a `dispute_reason`, moving verification to `DISPUTED`. Resolution then belongs to a `ComplianceOfficer` acting on a `DISPUTED` visit (otherwise `ERR_VISIT_NOT_DISPUTED`) by supplying `approved_minutes` between zero and the scheduled minutes inclusive (outside that range fails `ERR_INVALID_REQUEST`): the ruling sets `approved_minutes` and `verified_at` and runs the same reversal-then-final reconciliation, except the final credit takes `approved_minutes` in place of the actual minutes — the smallest of `approved_minutes`, the scheduled minutes, and the effective cap, rounded to fifteen-minute units. Silence resolves in the volunteer's favor by default: a completed visit left `UNVERIFIED` more than fourteen days past `actual_end` is deemed verified by the sweep, running the same reconciliation from `actual_minutes`.

Every posting lands in the hour ledger described in §2.9. Each row names its `handler_id`, links a `visit_id` unless it is an adjustment, carries its `kind` and signed `minutes`, and may carry a `note` — for an adjustment the `note` records the supplied `reason` label. A `ComplianceOfficer` posts manual adjustments with the target `handler_id`, a signed `minutes`, and a `reason`; an adjustment of zero minutes, or one that would take the handler's `lifetime_minutes` below zero, is rejected with `ERR_INVALID_ADJUSTMENT`. The ledger list accepts `handler_id`, `visit_id`, and `kind` filters.

Recognition accumulates from the ledger. The handler's `lifetime_minutes` — the floored algebraic sum over `PROVISIONAL`, `FINAL`, `REVERSAL`, and `ADJUSTMENT` rows alike — maps to the highest `recognition_tier` whose threshold it meets: `NONE` below fifteen hundred minutes, `BRONZE` at fifteen hundred, `SILVER` at six thousand, `GOLD` at fifteen thousand, and `PLATINUM` at thirty thousand, each threshold inclusive at the exact boundary. The recognition summary for a handler reports the `handler_id`, the `lifetime_minutes`, the derived `lifetime_hours` — minutes divided by sixty and displayed to two decimal places, rounded half-up — the current `recognition_tier`, the `next_tier` naming the next higher tier, and `minutes_to_next_tier` giving the additional lifetime minutes needed to reach it.

Facilities get a mirror-image summary. The demand summary for a facility reports the `facility_id`, the `open_request_count` of its requests standing `OPEN` or `OFFERED`, the `expired_last_90d` count of requests swept to `EXPIRED` whose `expired_on` falls on or after ninety days before today — the boundary date itself included — the `fulfilled_last_90d` count of requests reaching `FULFILLED` with `fulfilled_on` inside the same window, and the `unmet_demand_index` formed as the sum of the open count and the recently expired count.

### 3.9. Incident Response and Animal-Welfare Enforcement

Welfare holds pull an animal off the schedule without touching its credentials. A `ComplianceOfficer` places an `ACTIVE` animal on hold (otherwise `ERR_ANIMAL_NOT_ACTIVE`) by supplying the `hold_until` instant and a `reason`; the animal moves to `WELFARE_HOLD` with `welfare_hold_until` set from the payload and `welfare_hold_reason` recorded as `MANUAL`. Release by a `ComplianceOfficer` requires the animal on hold (otherwise `ERR_ANIMAL_NOT_ON_HOLD`) and clears both fields as the animal returns to `ACTIVE`; the sweep performs the same release automatically once the hold instant has passed, provided no incident filed on the animal's visits still stands `FILED`, `UNDER_REVIEW`, or `ESCALATED`. Incident escalation places holds automatically with `welfare_hold_until` fixed fourteen days out and `welfare_hold_reason` `INCIDENT_PRECAUTION`.

Anyone on the scene can raise the alarm: the handler or the facility's coordinator files an incident against a visit standing `IN_PROGRESS` or `COMPLETED` — a visit in any other state fails with `ERR_VISIT_NOT_COMPLETED` — by naming the `visit_id`, a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a `category` of `ANIMAL_STRESS`, `BITE_SCRATCH`, `INJURY`, `PROPERTY_DAMAGE`, or `PROTOCOL_BREACH`, and a free-text `description` of at least ten characters. The report records the filer's role in `filed_by_role` and starts `FILED`. The incident list accepts `visit_id`, `status`, and `severity` filters.

A `ComplianceOfficer` triages a `FILED` report (otherwise `ERR_INCIDENT_NOT_FILED`), stamping `triaged_by` with their `X-User-ID` and moving it to `UNDER_REVIEW`. Escalation from `UNDER_REVIEW` (otherwise `ERR_INCIDENT_NOT_UNDER_REVIEW`) moves the report to `ESCALATED` and fires the precaution cascade in four hops: the animal of the visit's team, if `ACTIVE`, moves to `WELFARE_HOLD` for fourteen days under `INCIDENT_PRECAUTION`; that team's certification standing `ACTIVE` or `RENEWAL_DUE` moves to `SUSPENDED` with `suspension_reason` `INCIDENT_PRECAUTION`; the team drops to `SUSPENDED` and every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `INCIDENT_PRECAUTION`, the animal's `forward_workload_minutes` decrementing per cancelled visit; and request-backed cancelled visits return their requests to `OPEN`.

Resolution closes the loop under segregated duties. A `ComplianceOfficer` resolves from `UNDER_REVIEW` or `ESCALATED` (otherwise `ERR_INCIDENT_NOT_RESOLVABLE`), and the resolving officer's `X-User-ID` must differ from the recorded `triaged_by` — a self-resolution fails with `ERR_SOD_VIOLATION`, the final check of the pipeline. The resolution call carries a `resolution_code`, and choosing `SUSPENSION` requires a `suspension_days` between one and three hundred sixty-five (missing or out of range fails `ERR_INVALID_REQUEST`). Resolution stamps `resolved_by` and moves the report to `RESOLVED`, and the code determines the aftermath. `NO_ACTION` releases the precaution: an animal hold standing with reason `INCIDENT_PRECAUTION` returns to `ACTIVE`, and a certification suspended under `INCIDENT_PRECAUTION` returns to `ACTIVE` with no gate re-check on this release — visits already cancelled are not restored. `WARNING` performs the same release and additionally increments the team's `warning_count` by one. `SUSPENSION` moves the certification to `SUSPENDED` with reason `INCIDENT_SUSPENSION` and a `suspension_until` of today plus `suspension_days`, and extends the animal's hold to today plus `suspension_days`. `REVOCATION` revokes the certification, dissolves the team, cancels the team's remaining `SCHEDULED` visits with `cancel_reason` `CERT_REVOKED`, and returns the animal from `WELFARE_HOLD` to `ACTIVE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state transition, scheduling, scoring, verification, and administrative action — return `200 OK`. The clock-set and sweep capabilities also return `200 OK`. Readers reconstruct each operation's full request and response contract from the narratives of §3 together with the global rules of §2; the table below fixes only the routing and authorization.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock (ISO 8601 UTC) | ProgramAdmin |
| POST | `/v1/_sweeps/run` | Run all deterministic time-based transitions in pinned order | ProgramAdmin |
| POST | `/v1/handlers` | Self-register a handler (status `APPLICANT`) | Anonymous |
| GET | `/v1/handlers/{id}` | Get a handler | Any authenticated role |
| GET | `/v1/handlers` | List handlers | Any authenticated role |
| POST | `/v1/handlers/{id}/approve` | Approve an applicant handler | ProgramAdmin |
| POST | `/v1/handlers/{id}/reject` | Reject an applicant handler | ProgramAdmin |
| POST | `/v1/handlers/{id}/suspend` | Suspend a handler (compliance) | ComplianceOfficer |
| POST | `/v1/handlers/{id}/reinstate` | Reinstate a suspended handler | ComplianceOfficer |
| POST | `/v1/handlers/{id}/retire` | Retire a handler; cascades teams to `DISSOLVED` and cancels their `SCHEDULED` visits | Handler, ProgramAdmin |
| GET | `/v1/handlers/{id}/recognition` | Computed recognition summary for a handler | Any authenticated role |
| POST | `/v1/animals` | Register an animal for the acting handler | Handler |
| GET | `/v1/animals/{id}` | Get an animal | Any authenticated role |
| GET | `/v1/animals` | List animals | Any authenticated role |
| POST | `/v1/animals/{id}/retire` | Retire an animal (owner handler only) | Handler |
| POST | `/v1/animals/{id}/welfare-hold` | Place an `ACTIVE` animal on welfare hold | ComplianceOfficer |
| POST | `/v1/animals/{id}/welfare-release` | Release an animal from welfare hold | ComplianceOfficer |
| POST | `/v1/vaccination-records` | Record a vaccination for an owned animal | Handler |
| GET | `/v1/vaccination-records/{id}` | Get a vaccination record | Any authenticated role |
| GET | `/v1/vaccination-records` | List vaccination records | Any authenticated role |
| POST | `/v1/vaccination-records/{id}/void` | Void a vaccination record | ComplianceOfficer |
| POST | `/v1/teams` | Form a team from an owned animal (one non-`DISSOLVED` team per animal) | Handler |
| GET | `/v1/teams/{id}` | Get a team | Any authenticated role |
| GET | `/v1/teams` | List teams | Any authenticated role |
| POST | `/v1/teams/{id}/dissolve` | Dissolve a team (no `SCHEDULED`/`IN_PROGRESS` visits; no non-terminal certification) | Handler |
| POST | `/v1/evaluators` | Create an evaluator | ProgramAdmin |
| GET | `/v1/evaluators/{id}` | Get an evaluator | Any authenticated role |
| GET | `/v1/evaluators` | List evaluators | Any authenticated role |
| PATCH | `/v1/evaluators/{id}` | Update evaluator status, specializations, or daily cap | ProgramAdmin |
| POST | `/v1/evaluations` | Request a team evaluation | Handler |
| GET | `/v1/evaluations/{id}` | Get an evaluation | Any authenticated role |
| GET | `/v1/evaluations` | List evaluations | Any authenticated role |
| POST | `/v1/evaluations/{id}/schedule` | Schedule an evaluation with an evaluator (buffered thirty-minute conflicts rejected) | ProgramAdmin |
| POST | `/v1/evaluations/{id}/score` | Score a concluded evaluation; routes to `PASSED` or `FAILED` per the composite rule | Evaluator |
| POST | `/v1/evaluations/{id}/appeal` | Appeal a `FAILED` evaluation within fourteen days | Handler |
| POST | `/v1/evaluations/{id}/cancel` | Cancel a non-terminal evaluation | Handler, ProgramAdmin |
| POST | `/v1/certifications` | Issue a `PROVISIONAL` certification from a `PASSED` evaluation | ProgramAdmin |
| GET | `/v1/certifications/{id}` | Get a certification | Any authenticated role |
| GET | `/v1/certifications` | List certifications | Any authenticated role |
| POST | `/v1/certifications/{id}/activate` | Activate a `PROVISIONAL` certification (vaccination and insurance gates) | ProgramAdmin |
| POST | `/v1/certifications/{id}/renew` | Renew a `RENEWAL_DUE` certification, or an `EXPIRED` one inside the ninety-day grace window | ProgramAdmin |
| POST | `/v1/certifications/{id}/suspend` | Suspend a certification; cascades team suspension and `SCHEDULED`-visit cancellation | ComplianceOfficer |
| POST | `/v1/certifications/{id}/reinstate` | Reinstate a suspended certification (re-checks vaccination and insurance gates) | ComplianceOfficer |
| POST | `/v1/certifications/{id}/revoke` | Revoke a certification; team dissolves, visits cancelled | ComplianceOfficer |
| POST | `/v1/facilities` | Register a facility (status `PROSPECT`) | ProgramAdmin |
| GET | `/v1/facilities/{id}` | Get a facility | Any authenticated role |
| GET | `/v1/facilities` | List facilities | Any authenticated role |
| PATCH | `/v1/facilities/{id}` | Update facility rules; applies prospectively to new visits | ProgramAdmin |
| POST | `/v1/facilities/{id}/suspend` | Suspend a facility (manual: existing `SCHEDULED` visits are kept; new scheduling blocked) | ComplianceOfficer |
| POST | `/v1/facilities/{id}/reinstate` | Reinstate a suspended facility (requires an `ACTIVE` agreement) | ComplianceOfficer |
| POST | `/v1/facilities/{id}/terminate` | Terminate a facility; agreement terminated, visits cancelled, requests withdrawn | ProgramAdmin |
| GET | `/v1/facilities/{id}/demand-summary` | Computed unmet-demand summary for a facility | Any authenticated role |
| POST | `/v1/facility-agreements` | Draft a facility agreement (facility `PROSPECT → ONBOARDING`; one non-terminal agreement per facility) | ProgramAdmin |
| GET | `/v1/facility-agreements/{id}` | Get an agreement | Any authenticated role |
| GET | `/v1/facility-agreements` | List agreements | Any authenticated role |
| POST | `/v1/facility-agreements/{id}/submit` | Submit a draft agreement for facility signature | ProgramAdmin |
| POST | `/v1/facility-agreements/{id}/sign-facility` | Facility countersigns the agreement | FacilityCoordinator |
| POST | `/v1/facility-agreements/{id}/sign-program` | Program countersigns; agreement activates and facility becomes `ACTIVE` | ProgramAdmin |
| POST | `/v1/facility-agreements/{id}/terminate` | Terminate an `ACTIVE` agreement; cascades facility suspension, visit cancellation, request withdrawal | ProgramAdmin, FacilityCoordinator |
| POST | `/v1/facility-agreements/{id}/withdraw` | Withdraw a pre-activation agreement | ProgramAdmin |
| POST | `/v1/orientation-records` | Assign a team to facility orientation (facility from `X-User-ID`) | FacilityCoordinator |
| GET | `/v1/orientation-records/{id}` | Get an orientation record | Any authenticated role |
| GET | `/v1/orientation-records` | List orientation records | Any authenticated role |
| POST | `/v1/orientation-records/{id}/complete` | Mark orientation completed; `expires_on` set one year out | FacilityCoordinator |
| POST | `/v1/orientation-records/{id}/reassign` | Re-assign an `EXPIRED` orientation (cyclic) | FacilityCoordinator |
| POST | `/v1/insurance-policies` | Register a liability insurance policy (`PENDING`) | Handler |
| GET | `/v1/insurance-policies/{id}` | Get a policy | Any authenticated role |
| GET | `/v1/insurance-policies` | List policies | Any authenticated role |
| POST | `/v1/insurance-policies/{id}/verify` | Verify a `PENDING` policy (one `ACTIVE` policy per handler) | ProgramAdmin |
| POST | `/v1/insurance-policies/{id}/cancel` | Cancel a policy; insurance-lapse cascade suspends certifications and cancels visits | Handler, ProgramAdmin |
| POST | `/v1/liability-waivers` | Sign a facility liability waiver for an owned team | Handler |
| GET | `/v1/liability-waivers/{id}` | Get a waiver | Any authenticated role |
| GET | `/v1/liability-waivers` | List waivers | Any authenticated role |
| POST | `/v1/liability-waivers/{id}/void` | Void a `SIGNED` waiver (prospective: blocks new visits; existing visits unaffected) | ComplianceOfficer |
| POST | `/v1/visit-requests` | Post a visit request (facility from `X-User-ID`) | FacilityCoordinator |
| GET | `/v1/visit-requests/{id}` | Get a visit request | Any authenticated role |
| GET | `/v1/visit-requests` | List visit requests | Any authenticated role |
| POST | `/v1/visit-requests/{id}/offers` | Offer an `OPEN` request to an eligible team (OCC on request version) | ProgramAdmin |
| POST | `/v1/visit-requests/{id}/accept` | Offered team's handler accepts; creates the `SCHEDULED` visit after re-running all visit gates | Handler |
| POST | `/v1/visit-requests/{id}/decline` | Offered team's handler declines; request cycles back to `OPEN` | Handler |
| POST | `/v1/visit-requests/{id}/withdraw` | Withdraw an `OPEN`/`OFFERED` request | FacilityCoordinator |
| GET | `/v1/visit-requests/{id}/candidate-teams` | Ranked eligible candidate teams for a request (score descending, `created_at` ascending tie-break; empty pool yields an empty array) | ProgramAdmin |
| POST | `/v1/visits` | Directly schedule a visit (OCC on team version); runs the full gate chain | ProgramAdmin |
| GET | `/v1/visits/{id}` | Get a visit | Any authenticated role |
| GET | `/v1/visits` | List visits | Any authenticated role |
| POST | `/v1/visits/{id}/check-in` | Check in within the window from fifteen minutes before `scheduled_start` through `scheduled_end` | Handler |
| POST | `/v1/visits/{id}/check-out` | Check out; completes the visit, posts provisional credit, sets the rest block, fulfills the request | Handler |
| POST | `/v1/visits/{id}/cancel` | Cancel a `SCHEDULED` visit; late-cancel penalty tiers; request reopens | Handler, ProgramAdmin, FacilityCoordinator |
| POST | `/v1/visits/{id}/verify` | Facility verifies a completed visit; provisional credit reversed, final credit posted | FacilityCoordinator |
| POST | `/v1/visits/{id}/dispute` | Facility disputes a completed visit | FacilityCoordinator |
| POST | `/v1/visits/{id}/resolve-dispute` | Compliance resolves a dispute with approved minutes; final credit computed from them | ComplianceOfficer |
| POST | `/v1/incident-reports` | File an incident against an `IN_PROGRESS` or `COMPLETED` visit | Handler, FacilityCoordinator |
| GET | `/v1/incident-reports/{id}` | Get an incident report | Any authenticated role |
| GET | `/v1/incident-reports` | List incident reports | Any authenticated role |
| POST | `/v1/incident-reports/{id}/triage` | Triage a filed incident (records `triaged_by`) | ComplianceOfficer |
| POST | `/v1/incident-reports/{id}/escalate` | Escalate; precaution cascade: animal hold, certification suspension, visit cancellation, request reopen | ComplianceOfficer |
| POST | `/v1/incident-reports/{id}/resolve` | Resolve with a resolution code; resolver must differ from triager | ComplianceOfficer |
| GET | `/v1/hour-credits/{id}` | Get an hour-credit ledger row | Any authenticated role |
| GET | `/v1/hour-credits` | List hour-credit ledger rows | Any authenticated role |
| POST | `/v1/hour-credits/adjustments` | Post a manual hour adjustment (signed minutes; lifetime floored at zero) | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below fixes each error identifier and its HTTP status. The conditions that trigger each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_HANDLER_NOT_FOUND` | 404 Not Found |
| `ERR_ANIMAL_NOT_FOUND` | 404 Not Found |
| `ERR_TEAM_NOT_FOUND` | 404 Not Found |
| `ERR_EVALUATOR_NOT_FOUND` | 404 Not Found |
| `ERR_EVALUATION_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_VACCINATION_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ORIENTATION_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_VISIT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOUR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_HANDLER_NOT_APPLICANT` | 409 Conflict |
| `ERR_HANDLER_NOT_ACTIVE` | 409 Conflict |
| `ERR_HANDLER_NOT_SUSPENDED` | 409 Conflict |
| `ERR_ANIMAL_NOT_ACTIVE` | 409 Conflict |
| `ERR_ANIMAL_NOT_ON_HOLD` | 409 Conflict |
| `ERR_ANIMAL_NOT_RETIRABLE` | 409 Conflict |
| `ERR_ANIMAL_HAS_ACTIVE_TEAM` | 409 Conflict |
| `ERR_TEAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_TEAM_NOT_FORMING` | 409 Conflict |
| `ERR_TEAM_HAS_SCHEDULED_VISITS` | 409 Conflict |
| `ERR_TEAM_HAS_ACTIVE_CERTIFICATION` | 409 Conflict |
| `ERR_EVALUATOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_EVALUATOR_SPECIES_MISMATCH` | 409 Conflict |
| `ERR_EVALUATION_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_EVALUATION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_EVALUATION_NOT_FAILED` | 409 Conflict |
| `ERR_EVALUATION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_EVALUATION_NOT_PASSED` | 409 Conflict |
| `ERR_EVALUATION_TEAM_MISMATCH` | 409 Conflict |
| `ERR_CERT_NOT_PROVISIONAL` | 409 Conflict |
| `ERR_CERT_NOT_RENEWABLE` | 409 Conflict |
| `ERR_CERT_NOT_SUSPENDABLE` | 409 Conflict |
| `ERR_CERT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_SUSPENSION_NOT_ELAPSED` | 409 Conflict |
| `ERR_CERT_NOT_REVOKABLE` | 409 Conflict |
| `ERR_CERT_NOT_ACTIVE` | 409 Conflict |
| `ERR_VACCINATION_NOT_VALID` | 409 Conflict |
| `ERR_FACILITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_FACILITY_NOT_SUSPENDED` | 409 Conflict |
| `ERR_FACILITY_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_AGREEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_AGREEMENT_NOT_AWAITING_FACILITY` | 409 Conflict |
| `ERR_AGREEMENT_NOT_AWAITING_PROGRAM` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_ORIENTATION_NOT_ASSIGNED` | 409 Conflict |
| `ERR_ORIENTATION_NOT_EXPIRED` | 409 Conflict |
| `ERR_POLICY_NOT_PENDING` | 409 Conflict |
| `ERR_POLICY_WINDOW_INVALID` | 409 Conflict |
| `ERR_POLICY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_WAIVER_NOT_SIGNED` | 409 Conflict |
| `ERR_REQUEST_NOT_OPEN` | 409 Conflict |
| `ERR_REQUEST_NOT_OFFERED` | 409 Conflict |
| `ERR_REQUEST_NOT_WITHDRAWABLE` | 409 Conflict |
| `ERR_VISIT_NOT_SCHEDULED` | 409 Conflict |
| `ERR_VISIT_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_VISIT_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_VISIT_NOT_COMPLETED` | 409 Conflict |
| `ERR_VISIT_ALREADY_RESOLVED` | 409 Conflict |
| `ERR_VISIT_NOT_DISPUTED` | 409 Conflict |
| `ERR_INCIDENT_NOT_FILED` | 409 Conflict |
| `ERR_INCIDENT_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_INCIDENT_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_ANIMAL_WELFARE_HOLD` | 403 Forbidden |
| `ERR_ANIMAL_REST_PERIOD` | 403 Forbidden |
| `ERR_WORKLOAD_LIMIT_EXCEEDED` | 403 Forbidden |
| `ERR_DAILY_VISIT_LIMIT_EXCEEDED` | 403 Forbidden |
| `ERR_SPECIES_NOT_PERMITTED` | 403 Forbidden |
| `ERR_VACCINATION_MISSING` | 403 Forbidden |
| `ERR_VACCINATION_EXPIRED` | 403 Forbidden |
| `ERR_NO_ACTIVE_AGREEMENT` | 409 Conflict |
| `ERR_ORIENTATION_NOT_COMPLETED` | 409 Conflict |
| `ERR_WAIVER_NOT_ON_FILE` | 409 Conflict |
| `ERR_VISIT_IN_PAST` | 409 Conflict |
| `ERR_TEAM_SCHEDULING_CONFLICT` | 409 Conflict |
| `ERR_EVALUATOR_SCHEDULING_CONFLICT` | 409 Conflict |
| `ERR_EVALUATION_SCHEDULE_IN_PAST` | 409 Conflict |
| `ERR_EVALUATION_DURATION_INVALID` | 409 Conflict |
| `ERR_EVALUATION_NOT_CONCLUDED` | 409 Conflict |
| `ERR_EVALUATION_APPEAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CHECKIN_TOO_EARLY` | 409 Conflict |
| `ERR_CHECKIN_WINDOW_PASSED` | 409 Conflict |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_AGREEMENT_TERM_PASSED` | 409 Conflict |
| `ERR_ORIENTATION_DATE_FUTURE` | 409 Conflict |
| `ERR_NO_ACTIVE_INSURANCE` | 402 Payment Required |
| `ERR_INSURANCE_COVERAGE_INADEQUATE` | 402 Payment Required |
| `ERR_VISIT_DURATION_INVALID` | 422 Unprocessable Entity |
| `ERR_VISIT_DURATION_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FACILITY_WEEKLY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EVALUATOR_DAILY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ACTIVE_CERTIFICATION_EXISTS` | 422 Unprocessable Entity |
| `ERR_ACTIVE_POLICY_EXISTS` | 422 Unprocessable Entity |
| `ERR_WAIVER_ALREADY_EXISTS` | 422 Unprocessable Entity |
| `ERR_ACTIVE_TEAM_EXISTS` | 422 Unprocessable Entity |
| `ERR_ACTIVE_AGREEMENT_EXISTS` | 422 Unprocessable Entity |
| `ERR_RENEWAL_VISIT_MINIMUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_TEAM_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_INVALID_ADJUSTMENT` | 422 Unprocessable Entity |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
