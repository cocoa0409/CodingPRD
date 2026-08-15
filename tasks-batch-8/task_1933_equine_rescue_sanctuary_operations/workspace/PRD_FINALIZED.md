# Equine Rescue Sanctuary API — Product Requirements Document

## 1. Introduction

An equine rescue nonprofit lives or dies by operational discipline: every horse that arrives at the gate carries a medical history that must be reconstructed under quarantine, a rehabilitation trajectory that must be planned and evidenced, and an eventual placement decision — adoption into a vetted home, or lifetime sanctuary care funded by sponsors — that must survive audits from donors, grantmakers, and regulators. This document specifies the API that runs that operation end to end. The system covers intake evaluation and quarantine protocol, rehabilitation planning with veterinary and farrier scheduling, the adoption application pipeline with home checks and post-adoption follow-up visits, lifetime care cost planning for non-adoptable sanctuary residents, hay and feed inventory with seasonal purchasing, volunteer barn shift scheduling, a per-horse sponsorship program, and a deliberately slow, multi-signature euthanasia and end-of-life decision policy.

Several of these concerns collide on the same records. A sponsorship pledge changes an adoption fee; a fever reading extends a quarantine; a failed follow-up visit unwinds an adoption into a refund, a return, and a fresh quarantine protocol; a single euthanasia execution cancels sponsorships, closes care plans, ends stall occupancy, and clears a practitioner's calendar in one atomic cascade. The API therefore treats the horse record as the consistency anchor: plan-creation writes carry optimistic-concurrency guards against it, state transitions propagate outward from it, and every mutation is versioned so that no client ever acts on a stale view of an animal.

All resources are mounted under the `/rescue-ops` prefix. This document is the sole normative source for implementers: §2 defines system-wide contracts, §3 narrates the business workflows in which those contracts come alive, §4 lists the endpoint surface, and §5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Ten roles exist, spelled exactly as follows: `SanctuaryDirector`, `IntakeCoordinator`, `Veterinarian`, `Farrier`, `AdoptionOfficer`, `Adopter`, `Sponsor`, `BarnManager`, `VolunteerCoordinator`, and `Volunteer`. After authentication, the caller's role must appear in the target endpoint's authorized-role list; otherwise the request fails with `ERR_FORBIDDEN` (HTTP 403).

Identity resolution distinguishes two kinds of role. For entity-backed roles, `X-User-ID` must be the `id` of an existing persisted entity, and ownership checks on any resource that references that entity compare the resource's foreign-key field to `X-User-ID`. Specifically: when `X-User-Role` is `Adopter`, `X-User-ID` is the `id` of an existing `Adopter`; when it is `Sponsor`, the `id` of an existing `Sponsor`; when it is `Volunteer`, the `id` of an existing `Volunteer`; when it is `Veterinarian`, the `id` of an existing `Practitioner` whose `specialty` is `VETERINARIAN`; and when it is `Farrier`, the `id` of an existing `Practitioner` whose `specialty` is `FARRIER`. An entity-backed identity that does not resolve — no such entity, or a practitioner whose specialty does not match the declared role — is rejected with `ERR_FORBIDDEN`. Ownership-scoped behavior follows from this: an `Adopter` may submit applications only under their own `adopter_id`, withdraw and pay fees only on their own applications, and read only their own adopter record; a `Sponsor` may create, activate, reinstate, or cancel only sponsorships whose `sponsor_id` equals their own id, and may read only their own sponsor record; a `Volunteer` claims and releases shifts only for themselves and reads only their own volunteer record; and a practitioner confirms or completes only appointments booked against their own id.

For the remaining roles — `SanctuaryDirector`, `IntakeCoordinator`, `AdoptionOfficer`, `BarnManager`, and `VolunteerCoordinator` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `completed_by_user_id` on a completed home check or evaluation) but never compares it to any entity's `id`.

One exemption exists to identity resolution, and it is what allows new participants into the system. The three registration endpoints — `POST /rescue-ops/adopters`, `POST /rescue-ops/sponsors`, and `POST /rescue-ops/volunteers` — are identity-establishing: on these calls `X-User-ID` is not resolved against any existing entity, the server mints the new entity's `id`, and the caller adopts that minted id thereafter.

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

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items before returning the page and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Sanctuary Logical Clock

Time inside this system is a server-side logical clock, never wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `SanctuaryDirector`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant and the response reports the resulting `current_utc`. Every piece of date arithmetic in this document — quarantine duration windows, cooling-off periods, document validity windows, refund windows, seasonal multipliers, "within N days" freshness checks — evaluates against this logical clock.

### 2.5. Common Resource Properties and the Append-Only Ledgers

All primary resources carry a standard set of system-managed fields:

- `id` (string): a server-minted UUID rendered in the canonical hyphenated 8-4-4-4-12 hexadecimal form (for example, `550e8400-e29b-41d4-a716-446655440000`), with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, captured at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification, including mutations performed by automatic cascades.

The same representation applies to every datetime-valued field the server returns: all business date and timestamp fields referenced throughout §3 — `start_date`, `end_date`, `cleared_at`, `recorded_at`, `evaluation_date`, `scheduled_date`, `submitted_at`, `completed_at`, `approved_at`, `finalized_at`, `activated_at`, `received_at`, `expiry_date`, `close_date` and `closed_date`, `shift_date`, `scheduled_start`, `scheduled_end`, `proposed_pickup_date`, `authorized_at`, `executed_at`, and the clock endpoint's `current_utc` — are likewise rendered as ISO 8601 UTC timestamps with three fractional digits (for example, `2026-08-01T00:00:00.000Z`).

Two resources are append-only ledgers and depart from this convention: a `DailyHealthLog` record and a `FeedDayClose` record carry only `id` and `created_at`. Both `updated_at` and `version` are absent on them — a health log, once recorded, is never updated, and a day-close record is never revisited.

### 2.6. Optimistic Concurrency on the Horse Record

Exactly two write operations participate in optimistic concurrency control, and both guard the same parent entity: creating a rehabilitation plan (`POST /rescue-ops/rehabilitation-plans`) and creating a sanctuary care plan (`POST /rescue-ops/sanctuary-care-plans`). Each of these creates supersedes the horse's current plan and bumps the horse's `version`, so each requires the client to supply `expected_horse_version` as a non-optional request field, carrying the caller's last-observed `version` of the target horse. If the supplied value does not equal the horse's current `version` at the moment of the write, the request is rejected as stale with `ERR_STALE_HORSE_VERSION` (HTTP 412): the caller's view predates the latest plan supersession — or some other horse mutation — and must be refreshed before retrying. Endpoints not named here do not accept a version field at all.

### 2.7. Validation Cascade and Failure Precedence

Every request is evaluated against a fixed, prioritized cascade of checks. Evaluation stops at the first failing tier, so the error a caller receives is always the highest-priority failure their request would have produced. The tiers run in this order:

1. **Header authentication.** `X-User-Role` and `X-User-ID` are present and the role is a declared role; failure is `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Identity resolution.** Entity-backed identities resolve as described in §2.1 (the three registration endpoints are exempt); failure is `ERR_FORBIDDEN` (HTTP 403).
3. **Role authorization.** The caller's role appears in the endpoint's authorized-role list; failure is `ERR_FORBIDDEN` (HTTP 403).
4. **Path existence.** Identifiers embedded in the URL path are resolved left to right; the first missing one fails with `ERR_NOT_FOUND` (HTTP 404).
5. **Body foreign-key existence.** Foreign keys supplied in the request body are resolved: an unknown `horse_id` fails with `ERR_HORSE_NOT_FOUND`, `adopter_id` with `ERR_ADOPTER_NOT_FOUND`, `practitioner_id` with `ERR_PRACTITIONER_NOT_FOUND`, `stall_id` with `ERR_STALL_NOT_FOUND`, `sponsor_id` with `ERR_SPONSOR_NOT_FOUND`, `application_id` with `ERR_APPLICATION_NOT_FOUND`, and `rehab_plan_id` with `ERR_REHAB_PLAN_NOT_FOUND` (all HTTP 404).
6. **Request shape.** Required fields are present, enum values belong to their declared sets, and numeric ranges hold — weight above zero, body condition scores within 1 through 9, quarantine minimum days within 1 through 60, suffering scores within 1 through 10, a pledge that is a positive integer, end times and dates strictly after their starts, non-empty skill lists. Violations fail with `ERR_INVALID_REQUEST` (HTTP 400).
7. **Optimistic concurrency.** On the two plan-creation endpoints, `expected_horse_version` must equal the horse's current `version`; failure is `ERR_STALE_HORSE_VERSION` (HTTP 412).
8. **State legality.** The target entity sits in a valid from-state for the requested transition, across every state machine, with terminal-state lockdown enforced; failure is `ERR_INVALID_STATE` (HTTP 409).
9. **Horse posture gates.** Adoption application creation requires the horse `ADOPTABLE` (`ERR_HORSE_NOT_ADOPTABLE`); appointment creation and confirmation, and sponsorship creation, activation, and reinstatement, require a resident horse (`ERR_HORSE_NOT_RESIDENT`); euthanasia case creation requires the horse to be in one of `REHABILITATION`, `ADOPTABLE`, `ADOPTION_PENDING`, or `SANCTUARY` (`ERR_INVALID_STATE`). All HTTP 409.
10. **Quarantine and day-close gates.** Releasing a horse requires its active protocol already `CLEARED`; re-quarantining while a protocol is still `ACTIVE` is refused; closing a calendar day that has already been closed is refused. Failures are `ERR_QUARANTINE_ACTIVE` or `ERR_DAY_ALREADY_CLOSED` (HTTP 409).
11. **Quarantine service restriction.** While a horse is `QUARANTINE`, only `VET_EXAM` appointments may be booked; failure is `ERR_QUARANTINE_SERVICE_RESTRICTED` (HTTP 422).
12. **Adopter standing.** A `BLOCKED` adopter may not submit an application and may not be approved; failure is `ERR_ADOPTER_BLOCKED` (HTTP 422).
13. **Segregation of duties.** The euthanasia certifier must differ from the proposer, and the adoption approver must differ from the officer who completed the passed home check; failure is `ERR_DUTY_SEGREGATION` (HTTP 422).
14. **Practitioner scheduling.** A practitioner's booked appointments must respect the overlap and buffer rules of §3.2; failure is `ERR_APPOINTMENT_OVERLAP` (HTTP 422).
15. **Stall occupancy.** Same-stall date overlap and the quarantine-barn gap rule of §3.1; failures are `ERR_STALL_OVERLAP` or `ERR_DISINFECTION_GAP_REQUIRED` (HTTP 422).
16. **Volunteer shift overlap.** A volunteer's assigned shifts on a date must not overlap as half-open intervals; failure is `ERR_SHIFT_OVERLAP` (HTTP 422).
17. **Cooling-off windows.** Adoption finalization and euthanasia execution must wait out their 72-hour cooling-off periods, subject to the emergency exception of §3.9; failure is `ERR_COOLING_OFF_ACTIVE` (HTTP 422).
18. **Document validity windows.** The passed home check must be fresh at approval (`ERR_HOME_CHECK_EXPIRED`), and the quarantine-clearance triplet of §3.1 applies (`ERR_RELEASE_DATE_NOT_REACHED`, `ERR_CLEARANCE_EXAM_STALE`, `ERR_FEVER_WITHIN_72H`). All HTTP 422. Within the quarantine-clearance family, the three sub-checks evaluate in a fixed order: the release-date check first, then the clearance-exam currency check, then the fever lookback.
19. **Pickup window.** The proposed pickup date must fall within fourteen days of finalization; failure is `ERR_PICKUP_WINDOW_EXCEEDED` (HTTP 422).
20. **Approval precedence.** No competing application further along the review pipeline may hold a strictly earlier submission timestamp; failure is `ERR_APPLICATION_PRECEDENCE_BLOCKED` (HTTP 422).
21. **Uniqueness.** One non-terminal application per adopter–horse pair (`ERR_DUPLICATE_APPLICATION`, HTTP 409); stall codes are unique (a duplicate `stall_code` fails with `ERR_INVALID_REQUEST`, HTTP 400); one `ACTIVE` quarantine protocol per horse (surfaced through the tier-10 gate as `ERR_QUARANTINE_ACTIVE`).
22. **Bonded-pair rules.** The pair-adoption and bonded-release conditions of §3.3 through §3.5; failure is `ERR_BONDED_PAIR_VIOLATION` (HTTP 422).
23. **Specialty, skill, and reliability gates.** The booked practitioner's specialty must cover the requested service (`ERR_SERVICE_SPECIALTY_MISMATCH`); the claiming volunteer must be `ACTIVE` (`ERR_VOLUNTEER_NOT_ACTIVE`), must clear the reliability floor (`ERR_RELIABILITY_TOO_LOW`), and must hold the required skill (`ERR_SKILL_MISMATCH`). All HTTP 422.
24. **Referential completion gates.** Plan completion with open appointments (`ERR_PLAN_HAS_OPEN_APPOINTMENTS`), over-receipt against a purchase order (`ERR_OVER_RECEIPT`), a third home-check attempt (`ERR_HOME_CHECK_LIMIT_EXCEEDED`), and stall-zone or inactive-stall mismatches (`ERR_STALL_ZONE_MISMATCH`). All HTTP 422.
25. **Fiscal settlement.** The adoption fee must be exactly settled at finalization (`ERR_ADOPTION_FEE_UNPAID`), fee payments must be positive integer amounts (`ERR_FEE_AMOUNT_INVALID`), and sponsorship pledges must meet the monthly minimum (`ERR_PLEDGE_BELOW_MINIMUM`). All HTTP 422.

### 2.8. Resident Posture and Terminal Lockdown

A horse is a **resident** whenever its `status` is anything other than `ADOPTED` or `DECEASED` — that is, `QUARANTINE`, `REHABILITATION`, `ADOPTABLE`, `ADOPTION_PENDING`, `SANCTUARY`, or `END_OF_LIFE_REVIEW`. Resident posture gates the booking of care appointments, the confirmation of those appointments, and the creation, activation, and reinstatement of sponsorships; breaches surface as `ERR_HORSE_NOT_RESIDENT`. Appointment confirmation is stricter still and additionally refuses a horse in `END_OF_LIFE_REVIEW`. Adoption workflows key on the narrower `ADOPTABLE` posture and surface `ERR_HORSE_NOT_ADOPTABLE`.

`DECEASED` is a terminal state with total lockdown: no transitions leave it, and every mutation endpoint targeting a deceased horse fails with `ERR_INVALID_STATE`. The same lockdown logic applies to the terminal states of the other state machines — a `COMPLETED` or `CANCELLED` appointment, home check, or follow-up visit; a `COMPLETED` evaluation; a `CLEARED` protocol; an `ENDED` stall assignment; a `FINALIZED`, `RETURN_COMPLETED`, `REJECTED`, or `WITHDRAWN` application; a `COMPLETED` or `SUPERSEDED` rehabilitation plan; a `SUPERSEDED` or `CLOSED` care plan; a `COMPLETED` or `CANCELLED` sponsorship; a `RECEIVED` purchase order; a `COMPLETED` or `NO_SHOW` shift; an `EXECUTED` or `OVERRIDDEN` euthanasia case — none accepts further transitions, and attempts fail with `ERR_INVALID_STATE`.

### 2.9. Numeric Precision, Rounding, and Monetary Representation

All monetary amounts are integer cents; no money field carries fractional cents. The single rounding method used everywhere in this system is **round half up**. Where a computation produces a stored monetary figure — adoption fees, purchase-order totals and surcharges, lot costs, care-plan costs — the result is rounded half up to zero decimal places, and §3 pins, per calculation, exactly which intermediate quantities are rounded and which are left unrounded until the final step. Feed weights stored on lots and day-close records carry two decimal places, rounded half up; each horse's daily ration carries one decimal place, rounded half up. Unit feed prices may carry fractional cents as supplied. Datetime comparisons (quarantine windows, cooling-off deadlines, validity windows) are performed at minute precision, with boundary inclusivity stated per rule in §3.

### 2.10. Nested Resource Resolution

Requests that target resources through identifier-bearing paths are validated strictly left to right: the system resolves each path identifier in turn and rejects the request immediately with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, before any later identifier or any body-level rule is examined. Only after the full path has resolved does the cascade proceed to body foreign keys (tier 5 of §2.7), which carry their own per-resource 404 codes. This ordering guarantees that a request aimed at a nonexistent container never leaks information about what would have been wrong with its payload.

## 3. Business Logic & Workflows

### 3.1. Intake, Housing, and the Quarantine Watch

Every horse enters the system through an intake performed by an `IntakeCoordinator`. The intake payload carries the horse's `name`, its `sex` (one of `MARE`, `GELDING`, or `STALLION`), its `breed_class` (`LIGHT`, `DRAFT`, or `PONY` — the class that later drives the lifespan constant in lifetime care-cost projections), its `estimated_weight_lbs` (an integer above zero), its `age_years` at intake (zero or more), its `body_condition_score` on the Henneke scale (an integer from 1 to 9), and its `training_level` (`UNHANDLED`, `GREEN`, or `TRAINED_RIDDEN`). Three further inputs are optional: `temperament_score` (an integer from 1 to 10, defaulting to 5 when omitted), free-text `intake_reason`, and `bonded_companion_id`, which links the horse to another horse as a bonded-pair companion and stays null for unbonded animals.

A newly intaken horse lands in `QUARANTINE` status with `current_location` set to `QUARANTINE_STALL`, and the same act auto-creates an `ACTIVE` quarantine protocol for it: `min_days` of 14, `reason` of `INTAKE`, `start_date` stamped at the logical now, and `extension_days` starting at 0. A horse carries at most one `ACTIVE` protocol at any moment.

Intake also computes the horse's `daily_feed_ration_lbs`, and the same computation reruns whenever a later update touches `estimated_weight_lbs` or `body_condition_score`. The ration starts from two percent of the horse's `estimated_weight_lbs`. When the horse's `body_condition_score` is 3 or lower, that base is increased by thirty percent; when the score is 7 or higher, the base is instead reduced by twenty percent. The adjusted figure is then capped at two and a half percent of `estimated_weight_lbs` and floored at 4.0 pounds, and the stored ration is that result rounded half up to one decimal place. An `IntakeCoordinator` or `Veterinarian` may also correct the horse's assessment fields after intake — `estimated_weight_lbs`, `body_condition_score`, `temperament_score`, `training_level`, and `bonded_companion_id` — and each such update reruns the ration computation when weight or condition changed and increments the horse's `version`.

Housing is tracked separately from posture. A `SanctuaryDirector` registers each stall with a unique `stall_code` (a duplicate code is refused with `ERR_INVALID_REQUEST`), a `barn_zone` of `QUARANTINE_BARN`, `MAIN_BARN`, or `ISOLATION`, and an `active` flag that defaults to true; an inactive stall refuses new assignments with `ERR_STALL_ZONE_MISMATCH`. An `IntakeCoordinator` then assigns a horse to a stall by supplying `horse_id`, `stall_id`, a `start_date`, and optionally an `end_date` — a null `end_date` leaves the occupancy open-ended while the assignment remains `ACTIVE`. Occupancy windows are closed date intervals: the horse occupies the stall from `start_date` through `end_date` inclusive. Two rules police the calendar. First, any closed-interval overlap between assignments on the same stall is rejected with `ERR_STALL_OVERLAP`. Second, in the `QUARANTINE_BARN` zone only, at least one full gap day must separate the new assignment from the previous occupant's window — the disinfection gap — and its absence is rejected with `ERR_DISINFECTION_GAP_REQUIRED`. Zone and posture must also agree: a `QUARANTINE` horse may be assigned only into `QUARANTINE_BARN` stalls, and any other pairing fails with `ERR_STALL_ZONE_MISMATCH`. Ending an assignment takes an `end_date` that must not precede the assignment's `start_date` (`ERR_INVALID_REQUEST`) and moves it from `ACTIVE` to `ENDED`; assignments also end by cascade, with their `end_date` set to the adopting application's `proposed_pickup_date` at finalization or to the logical now at euthanasia execution.

While a horse lives under quarantine, its health is watched through an append-only daily log. An `IntakeCoordinator` or `Veterinarian` appends an entry with the `horse_id`, a rectal `temp_f` in Fahrenheit (accepted between 95.0 and 110.0), an `appetite` of `NORMAL`, `REDUCED`, or `NONE`, and optional free-text `notes`; the server stamps `recorded_at` at the logical now and the entry is never edited afterward. Two cascades key off this log and its clinical siblings. A fever reading — `temp_f` at or above 103.0 — on a horse with an `ACTIVE` protocol automatically adds 7 days to that protocol's `extension_days`; separately, completing a `MEDICAL` intake evaluation with an outcome of `FAIL` on a horse with an `ACTIVE` protocol adds the same 7-day extension. Manual extension is also possible: an `IntakeCoordinator` or `Veterinarian` extends a protocol by supplying `days` and a `reason`, growing `extension_days` by the supplied amount, provided the protocol is still `ACTIVE` (`ERR_INVALID_STATE` otherwise).

Intake evaluations themselves are scheduled with a `horse_id`, an `evaluation_type` of `MEDICAL`, `BEHAVIORAL`, or `FARRIERY`, and a `scheduled_date`, and begin life `SCHEDULED`. Completing one — a `Veterinarian`, `Farrier`, or `IntakeCoordinator` act, carrying an `outcome` of `PASS`, `FAIL`, or `CONDITIONAL` plus optional `findings` — moves it to `COMPLETED`, stamps `evaluation_date` at the logical now, and records the caller in `completed_by_user_id`.

Clearing a protocol is a `Veterinarian`'s call and is governed by a three-part timing rule evaluated in this fixed order. First, the logical now must have reached the protocol's `start_date` plus `min_days` plus `extension_days` days — arrival exactly at that instant is allowed — else `ERR_RELEASE_DATE_NOT_REACHED`. Second, the horse must have a `COMPLETED` `MEDICAL` intake evaluation whose `evaluation_date` falls within 48 hours of now — an exam exactly 48 hours old still counts — else `ERR_CLEARANCE_EXAM_STALE`. Third, no daily health log with `temp_f` at or above 103.0 may have been recorded strictly within the trailing 72 hours — a fever log exactly 72 hours old does not block clearance — else `ERR_FEVER_WITHIN_72H`. A successful clearance moves the protocol from `ACTIVE` to `CLEARED` and stamps `cleared_at`.

Release from quarantine belongs to the `IntakeCoordinator`, who names a `target_status` and may attach optional `notes`. Releasing to `REHABILITATION` requires the horse still in `QUARANTINE` (`ERR_INVALID_STATE`) and its active protocol already `CLEARED` (`ERR_QUARANTINE_ACTIVE`); the horse's `current_location` becomes `REHAB_PADDOCK` and its `version` increments. Releasing to `ADOPTABLE` adds two further gates: a `COMPLETED` `MEDICAL` evaluation with outcome `PASS` must exist (`ERR_INVALID_STATE`), and when `bonded_companion_id` is set, the companion horse must currently be `ADOPTABLE` or `ADOPTION_PENDING` (`ERR_BONDED_PAIR_VIOLATION`); an adoptable release moves the horse to `MAIN_PASTURE` with the same version increment.

A resident horse can also be sent back. Re-quarantine — again an `IntakeCoordinator` act, taking `min_days` and a free-text `reason` such as `EXPOSURE` — applies to a horse in `REHABILITATION`, `ADOPTABLE`, or `SANCTUARY` (`ERR_INVALID_STATE` from any other posture), is refused while another protocol is still `ACTIVE` (`ERR_QUARANTINE_ACTIVE`), creates a fresh `ACTIVE` protocol from the supplied values with `start_date` at now, returns the horse to `QUARANTINE` in the `QUARANTINE_STALL`, cancels every one of the horse's appointments still in `REQUESTED` or `CONFIRMED` with `cancellation_reason` recorded as `QUARANTINE_REENTRY`, and increments the horse's `version`.

### 3.2. Rehabilitation Plans and Practitioner Care

Clinical work is delivered by practitioners, registered by a `SanctuaryDirector` with a `name`, a `specialty` of `VETERINARIAN` or `FARRIER`, and an `active` flag defaulting to true. Inactive practitioners cannot be booked. Deactivating a practitioner — flipping `active` from true to false, which the same update endpoint can do alongside `name` changes — immediately cancels every appointment of theirs still in `REQUESTED` or `CONFIRMED`, with `cancellation_reason` recorded as `PRACTITIONER_INACTIVE`.

A horse in `REHABILITATION` works from a rehabilitation plan authored by a `Veterinarian`: the create call carries `horse_id`, the OCC guard `expected_horse_version` per §2.6, a free-text `goals` narrative, a `target_body_condition_score` from 1 to 9, and `planned_weeks` from 1 to 52. The horse must be in `REHABILITATION` (`ERR_INVALID_STATE`). Creating the new plan supersedes whichever of the horse's existing plans sits in `DRAFT` or `ACTIVE`, moving it to `SUPERSEDED`, and bumps the horse's `version`; the new plan itself begins in `DRAFT`. Activation (`DRAFT` → `ACTIVE`) requires the horse in `REHABILITATION` and no other `ACTIVE` plan for the same horse (`ERR_INVALID_STATE`), and stamps `activated_at`. Completion (`ACTIVE` → `COMPLETED`) is refused while any appointment linked to the plan through `rehab_plan_id` remains `REQUESTED` or `CONFIRMED` — surfaced as `ERR_PLAN_HAS_OPEN_APPOINTMENTS`. A plan's `completed_visit_count` starts at 0 and climbs by one each time a linked appointment completes.

Appointments bind a horse, a practitioner, and a time window. Booking — open to `IntakeCoordinator`, `Veterinarian`, and `Farrier` callers — takes `horse_id`, `practitioner_id`, a `service_type` of `VET_EXAM`, `VET_PROCEDURE`, `DENTAL`, `FARRIER_TRIM`, or `FARRIER_SHOEING`, a `scheduled_start`, and a `scheduled_end` that must come after the start, together describing a half-open interval beginning at `scheduled_start` and ending at `scheduled_end`; `rehab_plan_id` is optional in general but required when the visit is a plan-linked rehabilitation visit. A new appointment is `REQUESTED` with `billing_status` `UNBILLED`. Four gates guard the booking. The horse must be resident — not `ADOPTED` or `DECEASED` — else `ERR_HORSE_NOT_RESIDENT`. While the horse is `QUARANTINE`, only `VET_EXAM` may be booked, else `ERR_QUARANTINE_SERVICE_RESTRICTED`. The service family must match the practitioner's specialty — the veterinary services `VET_EXAM`, `VET_PROCEDURE`, and `DENTAL` require a `VETERINARIAN`, while `FARRIER_TRIM` and `FARRIER_SHOEING` require a `FARRIER` — else `ERR_SERVICE_SPECIALTY_MISMATCH`. And the practitioner's diary must stay sane: against every existing `REQUESTED` or `CONFIRMED` appointment of the same practitioner, the new half-open interval may neither overlap nor sit closer than fifteen minutes away — back-to-back slots with a fifteen-minute-or-longer gap are fine, anything tighter fails with `ERR_APPOINTMENT_OVERLAP`. Booking an inactive practitioner fails as `ERR_INVALID_STATE`.

The booked practitioner then drives the appointment through its life. Confirming (`REQUESTED` → `CONFIRMED`) requires the caller's `X-User-ID` to equal the appointment's `practitioner_id` with a role matching that practitioner's specialty (`ERR_FORBIDDEN`), the practitioner still active (`ERR_INVALID_STATE`), and the horse not in `ADOPTED`, `DECEASED`, or `END_OF_LIFE_REVIEW` (`ERR_HORSE_NOT_RESIDENT`). Completing (`CONFIRMED` → `COMPLETED`) again requires the caller to be that practitioner (`ERR_FORBIDDEN`), and does three things atomically: `billing_status` moves from `UNBILLED` to `BILLED`, `actual_cost_cents` is set from the completion input (which also accepts optional `outcome_notes`), and — when the appointment's `rehab_plan_id` names a plan that is `ACTIVE` — that plan's `completed_visit_count` increments. Cancellation, available to an `IntakeCoordinator` or `Veterinarian` with an optional `cancellation_reason`, takes an appointment from `REQUESTED` or `CONFIRMED` to `CANCELLED` and never bills: `billing_status` stays `UNBILLED`. Note that `billing_status` is a parallel dimension that evolves independently of the request lifecycle; only completion flips it, and completion is reachable solely from `CONFIRMED`.

Graduation is the veterinarian's verdict that a horse is ready to leave rehabilitation. Moving `REHABILITATION` → `ADOPTABLE` requires four conditions, each a state or evidence failure surfaced as `ERR_INVALID_STATE` except the last: the horse is in `REHABILITATION`; a rehabilitation plan for the horse exists in `COMPLETED` and none remains in `DRAFT` or `ACTIVE`; a `COMPLETED` `MEDICAL` intake evaluation with outcome `PASS` exists whose `evaluation_date` lies within 30 days of the logical now; and, when `bonded_companion_id` is set, the companion horse is `ADOPTABLE` or `ADOPTION_PENDING` (`ERR_BONDED_PAIR_VIOLATION`). Graduation moves the horse to `MAIN_PASTURE` and increments its `version`.

### 3.3. The Adoption Pipeline: Applications and Home Checks

Prospective adopters self-register under the `Adopter` role — an identity-establishing call per §2.1 — supplying `full_name`, `contact_email`, an `experience_level` of `NOVICE`, `INTERMEDIATE`, or `EXPERT`, and a `has_stall_facility` flag declaring whether they keep stalls of their own. A new adopter is `ACTIVE`. An `AdoptionOfficer` or `SanctuaryDirector` may later block an adopter (recording a `reason`), moving them `ACTIVE` → `BLOCKED`, and unblock them back to `ACTIVE`. While `BLOCKED`, an adopter can neither submit an application nor be approved on one; both attempts fail with `ERR_ADOPTER_BLOCKED`.

Submitting an application is the adopter's own act: the payload's `adopter_id` must equal the caller's `X-User-ID` (`ERR_FORBIDDEN` otherwise), alongside the target `horse_id`, a `proposed_pickup_date`, and an optional `adopt_with_bonded_companion` flag defaulting to false. The horse must be `ADOPTABLE` (`ERR_HORSE_NOT_ADOPTABLE`). Each adopter–horse pair admits at most one non-terminal application: while an application from the same adopter for the same horse sits in `SUBMITTED`, `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`, `HOME_CHECK_PASSED`, or `APPROVED`, a fresh submission is refused with `ERR_DUPLICATE_APPLICATION`. Setting the pair flag on a horse with no `bonded_companion_id` is refused with `ERR_BONDED_PAIR_VIOLATION`. A created application is `SUBMITTED`, its `submitted_at` stamped at the logical now — the timestamp that later orders precedence — and its counters start at zero: `home_check_attempts` 0, `fee_paid_cents` 0, `refund_cents` 0.

An `AdoptionOfficer` picks the file up by starting review (`SUBMITTED` → `UNDER_REVIEW`). The pipeline then hinges on home checks. Scheduling one takes the `application_id` and a `scheduled_date`; the application must be `UNDER_REVIEW` (`ERR_INVALID_STATE`), and the attempt cap is hard: creating a home check while `home_check_attempts` has already reached 2 fails with `ERR_HOME_CHECK_LIMIT_EXCEEDED`. Each creation increments `home_check_attempts` by one and moves the application `UNDER_REVIEW` → `HOME_CHECK_SCHEDULED`; the check itself begins `SCHEDULED`.

Completing a home check is an `AdoptionOfficer` act carrying an `outcome` of `PASSED`, `FAILED`, or `CONDITIONAL` with optional `findings`; the check moves `SCHEDULED` → `COMPLETED`, stamps `completed_at` at the logical now, and records the completing officer in `completed_by_user_id`. The outcome then moves the owning application, provided the completed check is its latest. A `PASSED` outcome advances the application `HOME_CHECK_SCHEDULED` → `HOME_CHECK_PASSED`. A `FAILED` or `CONDITIONAL` outcome loops the application back to `UNDER_REVIEW` for another attempt — with one exception: a `FAILED` outcome when `home_check_attempts` has reached 2 skips the loop entirely and auto-rejects the application, moving it to `REJECTED` with `decision_reason` recorded as `HOME_CHECK_LIMIT`.

### 3.4. Approval, Fee Determination, and Settlement

Approval turns a vetted application into a financial commitment, and it is the most heavily guarded transition in the system. An `AdoptionOfficer` approves an application sitting in `HOME_CHECK_PASSED`. The guards evaluate in the cascade order of §2.7: the application must be in `HOME_CHECK_PASSED` (`ERR_INVALID_STATE`); the horse must be `ADOPTABLE` (`ERR_HORSE_NOT_ADOPTABLE`); the adopter must be `ACTIVE` (`ERR_ADOPTER_BLOCKED`); segregation of duties forbids the approving officer's `X-User-ID` from equaling the `completed_by_user_id` of the passed home check (`ERR_DUTY_SEGREGATION`); the latest completed home check's `completed_at` must lie within 180 days of the logical now (`ERR_HOME_CHECK_EXPIRED`); no other application for the same horse may sit in `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`, or `HOME_CHECK_PASSED` with a `submitted_at` strictly earlier than this application's — equal timestamps do not block — (`ERR_APPLICATION_PRECEDENCE_BLOCKED`); and when `adopt_with_bonded_companion` is set, the companion horse must be `ADOPTABLE` (`ERR_BONDED_PAIR_VIOLATION`).

Approval stamps `approved_at` at the logical now, snapshots `quoted_fee_cents` from the QUOTED variant of the fee calculation described below, and cascades onto the horse: `ADOPTABLE` → `ADOPTION_PENDING`, the horse's `active_application_id` set to the approved application, and the horse's `version` incremented. That `active_application_id` link is later cleared by rejection, withdrawal, finalization, or return.

The adoption fee follows a pinned four-step evaluation order, and both of its variants run exactly these steps. Step one computes a per-horse base from the horse's `age_years`: 95000 cents under 2 years of age, 85000 cents from 2 through 14, 60000 cents from 15 through 19, and 35000 cents at 20 or older; then adjusts for `training_level` — add 15000 cents for `TRAINED_RIDDEN`, subtract 10000 for `GREEN`, subtract 20000 for `UNHANDLED`; then adds a 5000-cent rehabilitation bonus if and only if the horse has a rehabilitation plan in `COMPLETED`. Step two applies the pair rule: when `adopt_with_bonded_companion` is set, step one is computed separately for the primary horse and for the bonded companion, the two figures are summed, and the fee becomes seventy-five percent of that sum, rounded half up to integer cents. Step three applies the sponsor subsidy: when the primary horse's `ACTIVE` sponsorships sum `monthly_pledge_cents` to at least 19250 cents, the fee is reduced by ten percent — multiplied by 0.90 and rounded half up — and only the primary horse's sponsorships ever count here. Step four fixes the representation: the result is integer cents, every input is an exact multiple of one cent, and so the rounding is a no-op for valid data, but it is pinned nonetheless. The QUOTED variant runs at approval and is frozen into `quoted_fee_cents`, evaluated against sponsorship and companion state as of `approved_at`. The FINAL variant reruns at finalization and is written to `final_fee_cents`; a sponsor lapse or cancellation, or a companion status change between approval and finalization, legitimately changes the number.

Settlement happens through payments the adopter makes on their own application: the caller's `X-User-ID` must equal the application's `adopter_id` (`ERR_FORBIDDEN`), the application must be `APPROVED` (`ERR_INVALID_STATE`), and each payment's `amount_cents` must be a positive integer (`ERR_FEE_AMOUNT_INVALID`). Payments accumulate into `fee_paid_cents`.

### 3.5. Finalization, Follow-Up Visits, and the Return Cascade

Finalization is the point of no return, guarded by time, money, and pair conditions. An `AdoptionOfficer` finalizes an application in `APPROVED` (`ERR_INVALID_STATE` otherwise). At least 72 hours must have elapsed since `approved_at`, else `ERR_COOLING_OFF_ACTIVE`. The FINAL fee recomputed at that instant must equal the accumulated `fee_paid_cents` exactly — an underpaid or overpaid balance fails with `ERR_ADOPTION_FEE_UNPAID`. The `proposed_pickup_date` must fall no more than 14 days after the finalization instant, else `ERR_PICKUP_WINDOW_EXCEEDED`. And when `adopt_with_bonded_companion` is set, the companion must still be `ADOPTABLE` (`ERR_BONDED_PAIR_VIOLATION`).

A successful finalization stamps `final_fee_cents` with the FINAL recompute — which may differ from `quoted_fee_cents` — sets `finalized_at` to the logical now, moves the application `APPROVED` → `FINALIZED`, and fires the full adoption cascade on the horse. The horse must be `ADOPTION_PENDING` with its `active_application_id` pointing at this application (`ERR_INVALID_STATE` otherwise); it moves to `ADOPTED`, its `current_location` becomes `OFFSITE_ADOPTED`, its `active_application_id` clears to null, and its `version` increments. Its `ACTIVE` stall assignment ends with `end_date` set to the application's `proposed_pickup_date`. Every sponsorship of the horse in `PLEDGED`, `ACTIVE`, or `LAPSED` completes with `completion_reason` `ADOPTED`, and each such completion recomputes the sponsor's standing; completing an `ACTIVE` sponsorship additionally draws the horse's care-plan funding coverage down by that pledge, per §3.6. When the pair flag is set, the bonded companion moves `ADOPTABLE` → `ADOPTED` with the same sponsorship and stall cascades. Every other application for the same horse sitting in `SUBMITTED`, `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`, or `HOME_CHECK_PASSED` is auto-rejected with `decision_reason` `SUPERSEDED_BY_FINALIZED_ADOPTION`. Finally, three follow-up visits are auto-created for the application: `visit_type` `DAY_30`, `DAY_90`, and `DAY_180`, each `SCHEDULED`, with `scheduled_date` set 30, 90, and 180 days after `finalized_at` respectively.

Two softer exits remain available before this point. An `AdoptionOfficer` may reject an application in `SUBMITTED`, `UNDER_REVIEW`, `HOME_CHECK_SCHEDULED`, `HOME_CHECK_PASSED`, or `APPROVED`, recording the supplied `reason` in `decision_reason`. The adopter may withdraw from the same five states — the caller must own the application (`ERR_FORBIDDEN`) and may attach an optional `reason`. Either way the application lands in `REJECTED` or `WITHDRAWN`, and when the departed state was `APPROVED`, the horse cascade reverts: the horse whose `active_application_id` names this application returns from `ADOPTION_PENDING` to `ADOPTABLE`, the link clears, and the horse's `version` increments.

After finalization, the follow-up visits keep the placement honest. An `AdoptionOfficer` completes a `SCHEDULED` visit — the owning application must be `FINALIZED` (`ERR_INVALID_STATE`) — supplying an `outcome` of `PASSED` or `FAILED` with optional `findings`; the visit moves to `COMPLETED` with `completed_at` stamped. A `PASSED` outcome ends there. A `FAILED` outcome fires the return cascade, four links deep. Link one moves the application `FINALIZED` → `RETURN_COMPLETED`, records `decision_reason` as `RETURNED_AFTER_FAILED_FOLLOW_UP`, and computes `refund_cents`: when the logical now is within 90 days of `finalized_at`, the refund is half of `final_fee_cents` rounded half up; later than that, it is one quarter of `final_fee_cents` rounded half up. Link two moves the horse `ADOPTED` → `REHABILITATION` and sets its `current_location` to `QUARANTINE_STALL`, incrementing `version`. Link three auto-creates a fresh `ACTIVE` quarantine protocol for the returned horse with `min_days` 14, `reason` `AUTO_RETURN`, and `start_date` at now. Link four cancels every remaining `SCHEDULED` follow-up visit of the same application, moving each to `CANCELLED`.

### 3.6. Sanctuary Care and Sponsorship Funding

Some horses are declared non-adoptable and join the sanctuary permanently. A `SanctuaryDirector` designates a horse in `REHABILITATION` — supplying a `reason` — moving it to `SANCTUARY`, relocating it to the `SANCTUARY_PASTURE`, and incrementing its `version`.

Lifetime care for such a horse is planned through a sanctuary care plan. Creating one is a `SanctuaryDirector` act carrying `horse_id`, the OCC guard `expected_horse_version` per §2.6, and a `variant` of `ACTUARIAL` or `STRAIGHT_LINE`. The horse must be in `SANCTUARY` (`ERR_INVALID_STATE`). Creating a new plan supersedes the horse's existing plan in `DRAFT` or `APPROVED`, moving it to `SUPERSEDED`, and bumps the horse's `version`. Both cost variants are computed at creation from the horse's data, and the `variant` field selects which one is stored on the plan's `projected_months`, `monthly_cost_cents`, and `total_lifetime_cost_cents`.

The projection works as follows. Each breed class carries an assumed lifespan: 25 years for `LIGHT`, 22 for `DRAFT`, 28 for `PONY`. The plan's `projected_months` is the horse's remaining lifespan expressed in months — the breed lifespan in years minus the horse's `age_years`, multiplied by twelve. If that figure is zero or negative, the create is rejected with `ERR_INVALID_REQUEST`. Under the `STRAIGHT_LINE` variant, care costs a flat 38500 cents per month: `monthly_cost_cents` is 38500 and `total_lifetime_cost_cents` is the projected months times 38500, with no mortality weighting — which is why its totals exceed the actuarial figure for young horses. Under the `ACTUARIAL` variant, the projection walks month by month. The monthly cost depends on the horse's age band at the start of that month: 38500 cents under 15 years, 45200 from 15 through 19, 52800 from 20 through 24, and 61500 at 25 or older. Survival follows an annual rate chosen the same way: 0.97 under 20 years, 0.89 from 20 through 24, and 0.78 at 25 or older. For each month in the projection, the month's band cost is weighted by the probability the horse survives through that month — a compounding product in which, for every month from the first through the one being weighted, the annual survival rate applicable at the horse's age at the start of that month is raised to the one-twelfth power. The weighted monthly costs are summed, intermediate survival and cost values are never rounded, and only the final sum is rounded half up to integer cents to become `total_lifetime_cost_cents`; `monthly_cost_cents` is that total divided by the projected months, rounded half up to integer cents.

Funding attaches to the plan through sponsorships, and the plan tracks it continuously. `funding_coverage_cents` is the sum of `monthly_pledge_cents` over the horse's `ACTIVE` sponsorships — `PLEDGED` and `LAPSED` pledges do not count — recomputed on every sponsorship mutation, starting from 0. From coverage and cost, `funding_status` is derived: `UNFUNDED` when coverage is zero, `PARTIALLY_FUNDED` when coverage is above zero but below `monthly_cost_cents`, and `FUNDED` when coverage reaches or exceeds `monthly_cost_cents`. Approving a plan (`DRAFT` → `APPROVED`, a `SanctuaryDirector` act requiring the horse in `SANCTUARY`, else `ERR_INVALID_STATE`) recomputes both figures. Closing a plan — explicitly, with an optional `reason`, from `DRAFT` or `APPROVED` (`ERR_INVALID_STATE` from elsewhere), or by the euthanasia-execution cascade — moves it to `CLOSED`.

Sponsors self-register under the `Sponsor` role with a `name` and `contact_email`. A sponsor's `status` is computed, never set directly: `ACTIVE` while the sponsor holds at least one sponsorship in `PLEDGED`, `ACTIVE`, or `LAPSED`, and `INACTIVE` otherwise — so a freshly registered sponsor reads `INACTIVE` until their first non-terminal pledge, and the figure is recomputed on every sponsorship mutation.

A sponsorship begins when a `Sponsor` pledges: `sponsor_id` must equal the caller's `X-User-ID` (`ERR_FORBIDDEN`), `horse_id` names the beneficiary — which must be resident, not `ADOPTED` or `DECEASED` (`ERR_HORSE_NOT_RESIDENT`) — and `monthly_pledge_cents` must be at least 2500 cents (`ERR_PLEDGE_BELOW_MINIMUM`). The new sponsorship is `PLEDGED`, and the sponsor's status recomputes, turning `ACTIVE`. Activation (`PLEDGED` → `ACTIVE`) is open to the owning `Sponsor` or a `SanctuaryDirector`; a sponsor-role caller must own the sponsorship (`ERR_FORBIDDEN`), the horse must still be resident (`ERR_HORSE_NOT_RESIDENT`), `activated_at` stamps the first activation, the horse's care-plan coverage climbs by the pledge when a plan sits in `DRAFT` or `APPROVED`, and the sponsor's status recomputes. Lapsing (`ACTIVE` → `LAPSED`) is a `SanctuaryDirector`-only act and draws coverage back down by the pledge, since a lapsed pledge no longer counts. Reinstatement (`LAPSED` → `ACTIVE`) — again the owning sponsor or the director, with the same ownership and residency checks — adds the pledge back into coverage. Cancellation accepts a sponsorship from `PLEDGED`, `ACTIVE`, or `LAPSED` into `CANCELLED`, is open to the owning sponsor or the director, accepts an optional free-text `cancellation_reason` (the euthanasia cascade uses the fixed value `HORSE_DECEASED`), recomputes sponsor status in all three branches, and subtracts the pledge from coverage only when the cancelled sponsorship had been `ACTIVE`. Finally, when a horse is adopted, every one of its sponsorships in `PLEDGED`, `ACTIVE`, or `LAPSED` moves to `COMPLETED` with `completion_reason` `ADOPTED`; all three branches recompute sponsor status, and only the branch leaving `ACTIVE` also draws the horse's care-plan coverage down by the pledge.

### 3.7. Feed Purchasing, Supply Projection, and the Daily Close

The feed program runs on a purchase-to-drawdown loop operated by a `BarnManager`. A purchase order is drafted with a `feed_type` of `GRASS_HAY`, `ALFALFA`, `GRAIN`, or `SUPPLEMENT`, a `quantity_lbs` above zero, and a `unit_cents_per_lb` above zero that may carry fractional cents. The draft holds `status` `DRAFT`, `received_lbs` at 0, `actual_total_cents` at 0, and an `estimated_total_cents` computed once at creation as the ordered quantity times the unit price, rounded half up to integer cents — a single-rounding estimate. Marking the order moves it `DRAFT` → `ORDERED`, at which point its undelivered remainder starts counting toward the committed supply projection below.

Receipts arrive in lots. Each receipt against an order — taking `quantity_received_lbs` and an `expiry_date` — requires the order in `ORDERED` or `PARTIALLY_RECEIVED` (`ERR_INVALID_STATE`), and the cumulative `received_lbs` plus the new quantity must not exceed the ordered `quantity_lbs` (`ERR_OVER_RECEIPT`). Every receipt creates a feed lot: the received quantity becomes both the lot's `initial_lbs` — an immutable anchor for the feed conservation invariant — and its starting `quantity_lbs`; `expiry_date` comes from the input; `feed_type` and `unit_cents_per_lb` are copied from the order; `received_at` stamps the logical now; and the lot's `lot_cost_cents` is its `initial_lbs` times the unit price, rounded half up to integer cents. Per-lot rounding comes first: the order's `received_lbs` accrues by the received quantity and its `actual_total_cents` grows by each lot's already-rounded `lot_cost_cents` — a sum of rounded lots, never a rounding of the raw sum. While cumulative receipts fall short of the ordered quantity the order sits in `PARTIALLY_RECEIVED` (repeated partial receipts keep it there); the receipt that reaches the ordered quantity exactly moves it to `RECEIVED` and closes the books: `delivery_surcharge_cents` is eight percent of `actual_total_cents` rounded half up, and `grand_total_cents` is `actual_total_cents` plus that surcharge. The pinned order — per-lot rounding, then summation, then surcharge on the sum — matters: three lots of 333 lbs each at 7.5 cents per pound yield 2498 cents per lot and 7494 cents in total, whereas summing the raw product first would yield 7493; the two evaluation orders differ by a cent, and this system takes the per-lot order.

Each lot also records the order it arrived on as `purchase_order_id`, and the lot listing can be filtered by it. A lot remains usable through its `expiry_date` inclusive; its `quantity_lbs` drains through the daily close described below.

The supply summary is computed on read and returns a `summaries` array with one entry per feed type. Demand comes from residents only — horses in every status except `ADOPTED` and `DECEASED`. Each resident horse contributes its `daily_feed_ration_lbs` split three ways: seventy percent to hay, twenty percent to `GRAIN`, ten percent to `SUPPLEMENT`. The hay share goes entirely to `GRASS_HAY`, except for horses whose `body_condition_score` is 3 or lower, whose hay share splits evenly — half to `GRASS_HAY`, half to `ALFALFA`. The summed `daily_demand_lbs` per feed type is stored in the summary rounded half up to two decimal places. A seasonal multiplier then scales demand according to the calendar month of the computation: 1.25 from December through February, 1.00 from March through May, 0.90 from June through August, and 1.10 from September through November. Supply is measured two ways. Usable stock is the summed `quantity_lbs` of lots whose `expiry_date` is on or after now; inbound stock adds the undelivered remainder — `quantity_lbs` minus `received_lbs` — of every purchase order in `ORDERED` or `PARTIALLY_RECEIVED`. The tight figure, `days_of_supply_tight`, divides usable stock alone by the seasonally scaled daily demand and rounds half up to two decimals; the committed figure, `days_of_supply_committed`, adds inbound stock to the numerator, so identical inputs yield a larger committed figure whenever any order is open. When a feed type's daily demand is zero, both figures are null and `reorder_required` is false. Otherwise `reorder_required` is true exactly when the tight figure is strictly below 30 days — a reading of exactly 30.00 does not trigger a reorder.

Closing a day is the program's ops-run checkpoint, invoked by a `BarnManager` with a `close_date`. Each calendar date may be closed at most once across the whole system — a second close of the same date fails with `ERR_DAY_ALREADY_CLOSED`. The close walks each feed type independently and writes one `FeedDayClose` record per type, and the response reports the `closed_date` together with the per-type `consumed_lbs` and `wasted_lbs`. Per feed type the order of operations is fixed. Expiry waste comes first: every lot of that type whose `expiry_date` falls before the `close_date` is wasted down to zero on-hand, and the record's `wasted_lbs` is the sum of those remaining quantities. Demand is then computed as that feed type's `daily_demand_lbs` times the seasonal multiplier for the close date's month, rounded half up to two decimal places. Drawdown follows first-expiring-first-out: usable lots are drained in `expiry_date` ascending order, ties broken by `created_at` ascending. The record's `consumed_lbs` is the lesser of the rounded demand and the usable stock, and `shortfall_lbs` captures whatever demand the stock could not meet.

### 3.8. Volunteer Shifts and Reliability Standing

Volunteers self-register under the `Volunteer` role with a `name`, a `contact_email`, and a `skills` list — a non-empty subset of `FEEDING`, `CLEANING`, `HANDLING`, and `MAINTENANCE`. A new volunteer is `ACTIVE` with `completed_shift_count` and `no_show_count` at 0 and a `reliability_score` of 50.

Reliability is exact integer arithmetic: the score is 50, plus 5 for every completed shift, minus 20 for every no-show, clamped so it never falls below 0 or rises above 100. It is recomputed after every shift completion and every no-show.

Shifts are posted by a `VolunteerCoordinator` with a `shift_date`, a `start_time` and `end_time` in HH:MM 24-hour form (the end must come after the start, and the pair describes a half-open interval beginning at `start_time` and ending at `end_time`), a `barn_zone` of `QUARANTINE_BARN`, `MAIN_BARN`, `ISOLATION`, or `PASTURES`, and a `required_skill` of `FEEDING`, `CLEANING`, `HANDLING`, `MAINTENANCE`, or `ANY`. A new shift is `OPEN` with `volunteer_id` null.

Claiming is the volunteer's act and is gated four ways: the shift must be `OPEN` (`ERR_INVALID_STATE`); the caller's volunteer record must be `ACTIVE` (`ERR_VOLUNTEER_NOT_ACTIVE`); the caller's `reliability_score` must be at least 40 — exactly 40 is allowed — (`ERR_RELIABILITY_TOO_LOW`); and the shift's `required_skill` must be `ANY` or appear among the caller's `skills` (`ERR_SKILL_MISMATCH`). On top of that, the volunteer's day must stay coherent: no other `ASSIGNED` shift of the same volunteer on the same `shift_date` may overlap the claimed window as half-open time intervals, though adjacent back-to-back shifts are allowed with no buffer (`ERR_SHIFT_OVERLAP`). A successful claim moves the shift `OPEN` → `ASSIGNED` and sets `volunteer_id` to the caller. Releasing a shift — allowed only to the assigned volunteer (`ERR_FORBIDDEN`) and only from `ASSIGNED` — returns it to `OPEN` and clears `volunteer_id` to null.

A `VolunteerCoordinator` closes out assigned shifts. Completing one (`ASSIGNED` → `COMPLETED`) increments the volunteer's `completed_shift_count` by one and recomputes reliability. Marking a no-show (`ASSIGNED` → `NO_SHOW`) increments `no_show_count` by one, recomputes reliability, and — when the recomputed score falls below 20 — automatically moves the volunteer to `SUSPENDED`.

### 3.9. End-of-Life Governance

The euthanasia pathway is deliberately slow and deliberately segregated: the veterinarian who proposes a case may never certify it, certification and authorization are separate acts by separate roles, and a cooling-off period stands between authorization and execution unless two veterinarians attest an emergency.

A case opens when a `Veterinarian` proposes one for a horse, supplying `horse_id`, a `clinical_summary`, and a `suffering_score` from 1 to 10. The horse must be in `REHABILITATION`, `ADOPTABLE`, `ADOPTION_PENDING`, or `SANCTUARY` — horses in `QUARANTINE` or already `ADOPTED` are excluded — and any other posture fails with `ERR_INVALID_STATE`. The case is created `PROPOSED` with `proposing_practitioner_id` set from the caller, and the same act cascades onto the horse: the horse's `prior_status` captures its current status, its `status` moves to `END_OF_LIFE_REVIEW`, its `version` increments, and the case mirrors the capture on its own `prior_horse_status`.

Certification requires a second veterinarian. Concurring — a `decision` of `CONCUR` — moves the case `PROPOSED` → `CERTIFIED`; the certifier's `X-User-ID` must differ from the case's `proposing_practitioner_id` (`ERR_DUTY_SEGREGATION`) and must reference an active practitioner of specialty `VETERINARIAN` (`ERR_FORBIDDEN`); the case records the certifier in `certifying_practitioner_id`. When the case's `suffering_score` is 8 or higher and the certifier passes `emergency_attestation` as true, the case's `emergency_certified` flag becomes true — and only that combination sets it. Dissenting — a `decision` of `DISSENT`, under the same duty-segregation guard — moves the case `PROPOSED` → `OVERRIDDEN` and restores the horse as described for overturn below.

Authorization belongs to the `SanctuaryDirector`: a `CERTIFIED` case moves to `AUTHORIZED`, provided the horse still stands in `END_OF_LIFE_REVIEW` (`ERR_INVALID_STATE`), and stamps `authorized_at` — the cooling-off anchor.

Execution returns to a `Veterinarian`: the case must be `AUTHORIZED` (`ERR_INVALID_STATE`), at least 72 hours must have elapsed since `authorized_at` unless the case is `emergency_certified` — which bypasses the wait entirely — (`ERR_COOLING_OFF_ACTIVE`), and the caller must reference an active practitioner of specialty `VETERINARIAN` (`ERR_FORBIDDEN`). Execution stamps `executed_at`, moves the case to `EXECUTED`, and fires the deceased cascade on the horse: the horse moves to `DECEASED`, its `prior_status` clears to null, its `current_location` becomes `NOT_APPLICABLE`, and its `version` increments; every sponsorship of the horse in `PLEDGED`, `ACTIVE`, or `LAPSED` is cancelled with `cancellation_reason` `HORSE_DECEASED`, each cancellation triggering a sponsor-status recompute; every care plan of the horse in `DRAFT` or `APPROVED` closes; every appointment of the horse in `REQUESTED` or `CONFIRMED` is cancelled with `cancellation_reason` `HORSE_DECEASED`; and its `ACTIVE` stall assignment ends with `end_date` set to the logical now. `DECEASED` is terminal per §2.8.

At any point before execution the director may stop the process: overturning — with a `reason` recorded on the case as `overturn_reason` — moves a `PROPOSED` or `CERTIFIED` case to `OVERRIDDEN` (`ERR_INVALID_STATE` from any other state) and restores the horse. Restoration reads the captured `prior_status`: the horse's `status` returns to it, `prior_status` clears to null, `current_location` is restored by prior status — `REHAB_PADDOCK` for `REHABILITATION`, `MAIN_PASTURE` for `ADOPTABLE`, `MAIN_PASTURE` for `ADOPTION_PENDING`, `SANCTUARY_PASTURE` for `SANCTUARY` — and the horse's `version` increments.

## 4. Endpoint Definitions

Operations that create new resources — a horse, a protocol via re-quarantine, an evaluation, a health log, a plan, a practitioner, an appointment, a stall, an assignment, an adopter, an application, a home check, a sponsor, a sponsorship, a care plan, a purchase order, a volunteer, a shift, or a euthanasia case — return `201 Created`. Operations that modify an existing resource, drive a state transition, or advance the clock return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/rescue-ops/_clock/set_current_utc` | Advance the logical clock | SanctuaryDirector |
| POST | `/rescue-ops/horses` | Intake a horse | IntakeCoordinator |
| GET | `/rescue-ops/horses` | List horses with filters and pagination | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier, AdoptionOfficer, BarnManager, VolunteerCoordinator, Adopter, Sponsor |
| GET | `/rescue-ops/horses/{id}` | Get one horse | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier, AdoptionOfficer, BarnManager, VolunteerCoordinator, Adopter, Sponsor |
| PATCH | `/rescue-ops/horses/{id}` | Update horse assessment fields; recomputes ration | IntakeCoordinator, Veterinarian |
| POST | `/rescue-ops/horses/{id}/release-quarantine` | Release horse from quarantine to REHABILITATION or ADOPTABLE | IntakeCoordinator |
| POST | `/rescue-ops/horses/{id}/graduate-rehabilitation` | Graduate horse from rehabilitation to adoptable | Veterinarian |
| POST | `/rescue-ops/horses/{id}/designate-sanctuary` | Designate horse as non-adoptable sanctuary resident | SanctuaryDirector |
| POST | `/rescue-ops/horses/{id}/quarantine` | Re-quarantine a resident horse | IntakeCoordinator |
| POST | `/rescue-ops/intake-evaluations` | Schedule an evaluation | IntakeCoordinator, Veterinarian, Farrier |
| GET | `/rescue-ops/intake-evaluations` | List evaluations | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier |
| GET | `/rescue-ops/intake-evaluations/{id}` | Get one evaluation | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier |
| POST | `/rescue-ops/intake-evaluations/{id}/complete` | Complete an evaluation with outcome | Veterinarian, Farrier, IntakeCoordinator |
| GET | `/rescue-ops/quarantine-protocols` | List quarantine protocols | SanctuaryDirector, IntakeCoordinator, Veterinarian |
| GET | `/rescue-ops/quarantine-protocols/{id}` | Get one protocol | SanctuaryDirector, IntakeCoordinator, Veterinarian |
| POST | `/rescue-ops/quarantine-protocols/{id}/extend` | Manually extend quarantine | IntakeCoordinator, Veterinarian |
| POST | `/rescue-ops/quarantine-protocols/{id}/clear` | Clear quarantine per the release-timing rule | Veterinarian |
| POST | `/rescue-ops/daily-health-logs` | Append a health log; fever readings auto-extend quarantine | IntakeCoordinator, Veterinarian |
| GET | `/rescue-ops/daily-health-logs` | List health logs | SanctuaryDirector, IntakeCoordinator, Veterinarian |
| GET | `/rescue-ops/daily-health-logs/{id}` | Get one health log | SanctuaryDirector, IntakeCoordinator, Veterinarian |
| POST | `/rescue-ops/rehabilitation-plans` | Create a rehab plan (OCC on horse version); supersedes current plan | Veterinarian |
| GET | `/rescue-ops/rehabilitation-plans` | List rehab plans | SanctuaryDirector, IntakeCoordinator, Veterinarian |
| GET | `/rescue-ops/rehabilitation-plans/{id}` | Get one plan | SanctuaryDirector, IntakeCoordinator, Veterinarian |
| POST | `/rescue-ops/rehabilitation-plans/{id}/activate` | Activate a draft plan | Veterinarian |
| POST | `/rescue-ops/rehabilitation-plans/{id}/complete` | Complete an active plan | Veterinarian |
| POST | `/rescue-ops/practitioners` | Register a practitioner | SanctuaryDirector |
| GET | `/rescue-ops/practitioners` | List practitioners | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier, AdoptionOfficer |
| GET | `/rescue-ops/practitioners/{id}` | Get one practitioner | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier, AdoptionOfficer |
| PATCH | `/rescue-ops/practitioners/{id}` | Update practitioner; deactivation cancels open appointments | SanctuaryDirector |
| POST | `/rescue-ops/care-service-appointments` | Book a vet/farrier appointment | IntakeCoordinator, Veterinarian, Farrier |
| GET | `/rescue-ops/care-service-appointments` | List appointments | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier |
| GET | `/rescue-ops/care-service-appointments/{id}` | Get one appointment | SanctuaryDirector, IntakeCoordinator, Veterinarian, Farrier |
| POST | `/rescue-ops/care-service-appointments/{id}/confirm` | Assigned practitioner confirms | Veterinarian, Farrier |
| POST | `/rescue-ops/care-service-appointments/{id}/complete` | Assigned practitioner completes; bills and credits plan visit | Veterinarian, Farrier |
| POST | `/rescue-ops/care-service-appointments/{id}/cancel` | Cancel a requested/confirmed appointment | IntakeCoordinator, Veterinarian |
| POST | `/rescue-ops/stalls` | Register a stall | SanctuaryDirector |
| GET | `/rescue-ops/stalls` | List stalls | SanctuaryDirector, IntakeCoordinator, BarnManager |
| GET | `/rescue-ops/stalls/{id}` | Get one stall | SanctuaryDirector, IntakeCoordinator, BarnManager |
| POST | `/rescue-ops/stall-assignments` | Assign horse to stall | IntakeCoordinator |
| GET | `/rescue-ops/stall-assignments` | List stall assignments | SanctuaryDirector, IntakeCoordinator, BarnManager |
| GET | `/rescue-ops/stall-assignments/{id}` | Get one assignment | SanctuaryDirector, IntakeCoordinator, BarnManager |
| POST | `/rescue-ops/stall-assignments/{id}/end` | End an assignment | IntakeCoordinator |
| POST | `/rescue-ops/adopters` | Register an adopter (caller becomes that adopter) | Adopter |
| GET | `/rescue-ops/adopters` | List adopters | AdoptionOfficer, SanctuaryDirector |
| GET | `/rescue-ops/adopters/{id}` | Get one adopter (Adopter role only for own id) | AdoptionOfficer, SanctuaryDirector, Adopter |
| POST | `/rescue-ops/adopters/{id}/block` | Block an adopter | AdoptionOfficer, SanctuaryDirector |
| POST | `/rescue-ops/adopters/{id}/unblock` | Unblock an adopter | AdoptionOfficer, SanctuaryDirector |
| POST | `/rescue-ops/adoption-applications` | Submit an adoption application | Adopter |
| GET | `/rescue-ops/adoption-applications` | List applications | AdoptionOfficer, SanctuaryDirector, Adopter |
| GET | `/rescue-ops/adoption-applications/{id}` | Get one application | AdoptionOfficer, SanctuaryDirector, Adopter |
| POST | `/rescue-ops/adoption-applications/{id}/start-review` | Move application to review | AdoptionOfficer |
| POST | `/rescue-ops/adoption-applications/{id}/approve` | Approve after passed home check | AdoptionOfficer |
| POST | `/rescue-ops/adoption-applications/{id}/reject` | Reject an application | AdoptionOfficer |
| POST | `/rescue-ops/adoption-applications/{id}/withdraw` | Adopter withdraws own application | Adopter |
| POST | `/rescue-ops/adoption-applications/{id}/pay-fee` | Record a fee payment (accumulates) | Adopter |
| POST | `/rescue-ops/adoption-applications/{id}/finalize` | Finalize adoption; fires the adoption cascade | AdoptionOfficer |
| POST | `/rescue-ops/home-checks` | Schedule a home check for an application | AdoptionOfficer |
| GET | `/rescue-ops/home-checks` | List home checks | AdoptionOfficer, SanctuaryDirector |
| GET | `/rescue-ops/home-checks/{id}` | Get one home check | AdoptionOfficer, SanctuaryDirector |
| POST | `/rescue-ops/home-checks/{id}/complete` | Record home check outcome | AdoptionOfficer |
| GET | `/rescue-ops/follow-up-visits` | List follow-up visits | AdoptionOfficer, SanctuaryDirector |
| GET | `/rescue-ops/follow-up-visits/{id}` | Get one follow-up visit | AdoptionOfficer, SanctuaryDirector |
| POST | `/rescue-ops/follow-up-visits/{id}/complete` | Record follow-up outcome; FAILED fires the return cascade | AdoptionOfficer |
| POST | `/rescue-ops/sponsors` | Register a sponsor (caller becomes that sponsor) | Sponsor |
| GET | `/rescue-ops/sponsors` | List sponsors | SanctuaryDirector, AdoptionOfficer |
| GET | `/rescue-ops/sponsors/{id}` | Get one sponsor (Sponsor role only for own id) | SanctuaryDirector, AdoptionOfficer, Sponsor |
| POST | `/rescue-ops/sponsorships` | Create a sponsorship pledge | Sponsor |
| GET | `/rescue-ops/sponsorships` | List sponsorships | SanctuaryDirector, AdoptionOfficer, Sponsor |
| GET | `/rescue-ops/sponsorships/{id}` | Get one sponsorship | SanctuaryDirector, AdoptionOfficer, Sponsor |
| POST | `/rescue-ops/sponsorships/{id}/activate` | Activate a pledge | Sponsor, SanctuaryDirector |
| POST | `/rescue-ops/sponsorships/{id}/lapse` | Mark an active sponsorship lapsed | SanctuaryDirector |
| POST | `/rescue-ops/sponsorships/{id}/reinstate` | Reinstate a lapsed sponsorship | Sponsor, SanctuaryDirector |
| POST | `/rescue-ops/sponsorships/{id}/cancel` | Cancel a sponsorship | Sponsor, SanctuaryDirector |
| POST | `/rescue-ops/sanctuary-care-plans` | Create a lifetime care plan (OCC on horse version) | SanctuaryDirector |
| GET | `/rescue-ops/sanctuary-care-plans` | List care plans | SanctuaryDirector, AdoptionOfficer |
| GET | `/rescue-ops/sanctuary-care-plans/{id}` | Get one care plan | SanctuaryDirector, AdoptionOfficer |
| POST | `/rescue-ops/sanctuary-care-plans/{id}/approve` | Approve a draft care plan | SanctuaryDirector |
| POST | `/rescue-ops/sanctuary-care-plans/{id}/close` | Close a care plan | SanctuaryDirector |
| POST | `/rescue-ops/purchase-orders` | Create a seasonal purchase order | BarnManager |
| GET | `/rescue-ops/purchase-orders` | List purchase orders | SanctuaryDirector, BarnManager |
| GET | `/rescue-ops/purchase-orders/{id}` | Get one purchase order | SanctuaryDirector, BarnManager |
| POST | `/rescue-ops/purchase-orders/{id}/mark-ordered` | Place the order | BarnManager |
| POST | `/rescue-ops/purchase-orders/{id}/receive` | Receive against an order; creates a feed lot | BarnManager |
| GET | `/rescue-ops/feed-lots` | List feed lots | SanctuaryDirector, BarnManager |
| GET | `/rescue-ops/feed-lots/{id}` | Get one feed lot | SanctuaryDirector, BarnManager |
| GET | `/rescue-ops/feed-inventory/summary` | Per-feed-type supply summary with tight and committed days-of-supply | SanctuaryDirector, BarnManager |
| POST | `/rescue-ops/feed-inventory/close-day` | Close a calendar day: expiry waste then FEFO drawdown per feed type | BarnManager |
| GET | `/rescue-ops/feed-day-closes` | List day-close records | SanctuaryDirector, BarnManager |
| POST | `/rescue-ops/volunteers` | Register a volunteer (caller becomes that volunteer) | Volunteer |
| GET | `/rescue-ops/volunteers` | List volunteers | VolunteerCoordinator, SanctuaryDirector |
| GET | `/rescue-ops/volunteers/{id}` | Get one volunteer (Volunteer role only for own id) | VolunteerCoordinator, SanctuaryDirector, Volunteer |
| POST | `/rescue-ops/barn-shifts` | Create an open barn shift | VolunteerCoordinator |
| GET | `/rescue-ops/barn-shifts` | List barn shifts | VolunteerCoordinator, SanctuaryDirector, Volunteer |
| GET | `/rescue-ops/barn-shifts/{id}` | Get one shift | VolunteerCoordinator, SanctuaryDirector, Volunteer |
| POST | `/rescue-ops/barn-shifts/{id}/claim` | Volunteer claims an open shift | Volunteer |
| POST | `/rescue-ops/barn-shifts/{id}/release` | Assigned volunteer releases the shift | Volunteer |
| POST | `/rescue-ops/barn-shifts/{id}/complete` | Mark shift completed; credits volunteer reliability | VolunteerCoordinator |
| POST | `/rescue-ops/barn-shifts/{id}/mark-no-show` | Mark shift no-show; penalty and possible auto-suspension | VolunteerCoordinator |
| POST | `/rescue-ops/euthanasia-cases` | Propose an end-of-life case | Veterinarian |
| GET | `/rescue-ops/euthanasia-cases` | List euthanasia cases | SanctuaryDirector, Veterinarian |
| GET | `/rescue-ops/euthanasia-cases/{id}` | Get one case | SanctuaryDirector, Veterinarian |
| POST | `/rescue-ops/euthanasia-cases/{id}/certify` | Second veterinarian concurs or dissents | Veterinarian |
| POST | `/rescue-ops/euthanasia-cases/{id}/authorize` | Director authorizes; starts cooling-off | SanctuaryDirector |
| POST | `/rescue-ops/euthanasia-cases/{id}/execute` | Execute after cooling-off (or immediately when emergency-certified) | Veterinarian |
| POST | `/rescue-ops/euthanasia-cases/{id}/overturn` | Director overturns a proposed/certified case | SanctuaryDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_HORSE_NOT_FOUND` | 404 Not Found |
| `ERR_ADOPTER_NOT_FOUND` | 404 Not Found |
| `ERR_PRACTITIONER_NOT_FOUND` | 404 Not Found |
| `ERR_STALL_NOT_FOUND` | 404 Not Found |
| `ERR_SPONSOR_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_REHAB_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_HORSE_NOT_ADOPTABLE` | 409 Conflict |
| `ERR_HORSE_NOT_RESIDENT` | 409 Conflict |
| `ERR_QUARANTINE_ACTIVE` | 409 Conflict |
| `ERR_DAY_ALREADY_CLOSED` | 409 Conflict |
| `ERR_STALE_HORSE_VERSION` | 412 Precondition Failed |
| `ERR_QUARANTINE_SERVICE_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_ADOPTER_BLOCKED` | 422 Unprocessable Entity |
| `ERR_DUTY_SEGREGATION` | 422 Unprocessable Entity |
| `ERR_APPOINTMENT_OVERLAP` | 422 Unprocessable Entity |
| `ERR_STALL_OVERLAP` | 422 Unprocessable Entity |
| `ERR_DISINFECTION_GAP_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SHIFT_OVERLAP` | 422 Unprocessable Entity |
| `ERR_COOLING_OFF_ACTIVE` | 422 Unprocessable Entity |
| `ERR_HOME_CHECK_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CLEARANCE_EXAM_STALE` | 422 Unprocessable Entity |
| `ERR_FEVER_WITHIN_72H` | 422 Unprocessable Entity |
| `ERR_RELEASE_DATE_NOT_REACHED` | 422 Unprocessable Entity |
| `ERR_PICKUP_WINDOW_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_APPLICATION_PRECEDENCE_BLOCKED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_APPLICATION` | 409 Conflict |
| `ERR_BONDED_PAIR_VIOLATION` | 422 Unprocessable Entity |
| `ERR_SERVICE_SPECIALTY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SKILL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VOLUNTEER_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_RELIABILITY_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_HOME_CHECK_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PLAN_HAS_OPEN_APPOINTMENTS` | 422 Unprocessable Entity |
| `ERR_OVER_RECEIPT` | 422 Unprocessable Entity |
| `ERR_STALL_ZONE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_ADOPTION_FEE_UNPAID` | 422 Unprocessable Entity |
| `ERR_FEE_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_PLEDGE_BELOW_MINIMUM` | 422 Unprocessable Entity |
