# Nurse Staffing, Acuity & Float Assignment API — Product Requirements Document

## 1. Introduction

Hospitals staff their nursing units against a moving target: the patient census changes by the hour, the acuity mix of those patients changes by the shift, and the supply of available nurses is finite, credentialed, and expensive. A unit that starts the day adequately staffed can become critically short within a single admission wave, and the levers available to nursing administration — re-deriving required ratios from a fresh census, deploying float-pool nurses against validated competencies, and buying back coverage with premium incentive pay — each interact with overtime exposure, charge-nurse coverage rules, and a fixed per-unit incentive budget. On top of the operational problem sits a regulatory one: the staffing plan actually achieved each day must be reported to an external regulator, who may return the report for revision before accepting it.

This document specifies an API that manages that entire loop. It covers the configuration of nursing units, nurse profiles, and the acuity-to-ratio staffing matrix; the submission of census and acuity snapshots and the automatic recomputation cascade they trigger; the lifecycle of a shift from `OPEN` through `LOCKED`; the assignment lifecycle from proposal through acceptance, confirmation, and completion; synchronous float-pool deployment with deterministic candidate selection; premium incentive offers with budget reservation and settlement; one-to-one sitter coverage diverted from confirmed staff; weekly hours and overtime accounting; and the submission, return, and acceptance cycle of daily compliance reports. The intended readers are the engineers implementing the service and the administrators, charge nurses, staff nurses, float coordinators, and regulators whose workflows it formalizes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly across the API: identity and authorization, the response envelope, pagination, resource property conventions, the order in which validation failures surface, concurrency control, reconciliation cascades, numeric precision, the accounting week, the incentive budget ledger, and the scheduling-overlap convention.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is missing, or if the supplied role is not one of the roles declared below, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows:

- `NurseAdmin` — the hospital nursing administration office; owns configuration, scheduling, the incentive budget, and regulator reporting. When `X-User-Role` is `NurseAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `ChargeNurse` — a unit-level charge nurse with house-wide operational authority; submits acuity snapshots, proposes and confirms assignments, locks shifts, and manages sitter requests. When `X-User-Role` is `ChargeNurse`, `X-User-ID` is the `id` of the acting `Nurse`, and that nurse is understood to hold `charge_qualified` equal to true.
- `StaffNurse` — a staff or float-pool nurse acting on their own assignments and on incentive offers. When `X-User-Role` is `StaffNurse`, `X-User-ID` is the `id` of the acting `Nurse`; ownership checks on any resource that references a nurse compare the resource's `nurse_id` field to `X-User-ID`. Accepting or declining an assignment is only permitted to the nurse named on it: if `X-User-ID` does not equal the assignment's `nurse_id`, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- `FloatCoordinator` — the float pool coordinator; requests and releases float deployments. When `X-User-Role` is `FloatCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Regulator` — the external staffing regulator; reviews submitted compliance reports. When `X-User-Role` is `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

All five roles share read access: every GET endpoint in this API may be called by any declared role. Write operations are role-restricted as described throughout §3 and summarized in §4.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return: it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this API — nursing units, nurses, staffing matrix rules, acuity snapshots, shifts, assignments, float requests, incentive offers, sitter requests, and compliance reports — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): starts at its initial value on creation and increments by one with every mutation of the resource, including mutations driven by system cascades rather than direct client writes.

Because cascades are first-class in this domain — an acuity amendment recomputes a shift, a lock cancels pending assignments, a completion settles an offer — it is important to note that any such induced change to a resource refreshes that resource's `updated_at` and increments its `version`, exactly as a direct write would.

### 2.5. Request Validation Order and Error Precedence

When several things are wrong with a request, the order in which the system evaluates checks determines which error the caller sees. The pipeline below is evaluated in this exact order, and an earlier failure masks all later ones:

1. **User context.** The `X-User-ID` and `X-User-Role` headers are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The acting role appears in the endpoint's permitted role list — otherwise `ERR_UNAUTHORIZED_ROLE`.
3. **Path existence.** Resource identifiers in the URL path are resolved left to right; the first identifier that does not correspond to an existing resource yields its specific not-found error — `ERR_UNIT_NOT_FOUND`, `ERR_NURSE_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_FLOAT_REQUEST_NOT_FOUND`, `ERR_SITTER_REQUEST_NOT_FOUND`, or `ERR_REPORT_NOT_FOUND` — and no later check runs. A write targeting an assignment under a shift, for example, validates the shift before the assignment payload is considered. Across the API the path parameters are named `unitId`, `nurseId`, `snapshotId`, `shiftId`, `assignmentId`, `floatRequestId`, `offerId`, `sitterRequestId`, and `reportId`.
4. **Resource ownership.** For the nurse-facing response actions, `X-User-ID` must equal the assignment's `nurse_id` — otherwise `ERR_NOT_RESOURCE_OWNER`.
5. **Request shape.** Required fields are present, enum values are in-domain, numeric ranges are valid, an observation window's `end_at` is strictly after its `start_at`, and a week ledger query's `week_start` falls on a Monday — any violation yields `ERR_INVALID_REQUEST`.
6. **State preconditions.** The target resource's current state permits the requested transition (the assignment state errors, `ERR_SHIFT_NOT_OPEN`, `ERR_OFFER_INVALID_STATE`, `ERR_SITTER_INVALID_STATE`, `ERR_FLOAT_REQUEST_NOT_RELEASABLE`, `ERR_REPORT_INVALID_STATE`). The optimistic-concurrency check of §2.6 also lives in this tier and is evaluated after the state preconditions: a stale shift version surfaces as `ERR_STALE_SHIFT_VERSION` only once the state checks have passed.
7. **Business safety rules.** Competency, charge qualification, scheduling overlap, charge-slot capacity, the float skill-mix cap, sitter covering-assignment validity, the active-sitter lock on cancellation and completion, and the adequately-staffed gate on offer creation — the errors `ERR_COMPETENCY_NOT_HELD`, `ERR_NOT_CHARGE_QUALIFIED`, `ERR_SHIFT_OVERLAP`, `ERR_CHARGE_SLOT_TAKEN`, `ERR_SKILL_MIX_VIOLATION`, `ERR_NO_COVERING_ASSIGNMENT`, `ERR_COVERS_ACTIVE_SITTER`, and `ERR_SHIFT_ADEQUATELY_STAFFED`.
8. **Uniqueness and conditional-field rules.** One shift per unit, date, and code; one matrix rule per unit-type and acuity pair; at most one open offer per shift; one compliance report per date; and the home-unit conditional rule for nurses — `ERR_SHIFT_ALREADY_EXISTS`, `ERR_MATRIX_RULE_EXISTS`, `ERR_OFFER_ALREADY_ACTIVE`, `ERR_REPORT_ALREADY_EXISTS`, and `ERR_HOME_UNIT_RULE_VIOLATED`.
9. **Referential prerequisites.** All four staffing matrix rules for a unit type must exist before an acuity snapshot can be submitted (`ERR_MATRIX_RULE_MISSING`), and a `SUBMITTED` snapshot must exist for the slot before a shift can be created (`ERR_ACUITY_SNAPSHOT_REQUIRED`).
10. **Fiscal gates.** The incentive budget check on offer creation (`ERR_INCENTIVE_BUDGET_EXCEEDED`) runs last, after every other rule has passed.

### 2.6. Optimistic Concurrency Control on Shift Assignment Creation

Exactly one write operation in this API carries an optimistic-concurrency token: the creation of a direct shift assignment by a `ChargeNurse`. That request must include `expected_shift_version`, a non-optional field carrying the `version` of the shift as the client last observed it. If another writer has advanced the shift's version since that observation — by creating another assignment, or because an acuity amendment recomputed the shift — the client's view of the shift's staffing state is stale, and the create is rejected with `ERR_STALE_SHIFT_VERSION` (HTTP 412). This prevents a charge nurse from stacking an assignment onto a staffing picture they have not seen. No other endpoint accepts a version field; all other mutations execute against the current server-side state, guarded only by their state preconditions.

### 2.7. Posture-Driven Reconciliation and Cascade Consistency

A shift is a living aggregate whose staffing health is continuously reconciled rather than explicitly edited. The shift's `staffing_posture` is re-evaluated after every mutation of `counted_assignments`, `sitter_diversion_count`, `charge_covered`, or `required_nurses`, as long as the shift has not been locked. While unlocked, the shift's `status` is `STAFFED` exactly when the posture is `ADEQUATE`, and `OPEN` otherwise; the system flips the status between `OPEN` and `STAFFED` automatically as the posture crosses that line, without any client request on the shift itself.

Cascades propagate in both directions across the peer entities. A new acuity snapshot supersedes its predecessor, recomputes the matching shift's `required_nurses`, and advances the shift's `version` by one. Locking a shift resolves everything still pending against it: proposed assignments are cancelled and their float deployments released, and open incentive offers expire. Completing an incentive-funded assignment settles its offer and moves money between the unit's ledger accounts. Each such induced mutation independently refreshes the affected resource's `updated_at` and increments its `version`, per §2.4. Clients should therefore treat any write as potentially changing resources beyond the one addressed.

### 2.8. Precision, Rounding, and Units

All monetary amounts are represented as integer cents (`incentive_budget_cents`, `base_hourly_rate_cents`, `premium_reserve_cents`, `provisional_cost_cents`, `final_cost_cents`, and the like); there are no fractional cents anywhere in the system. Every conversion that produces a monetary value rounds **half-up to whole cents**. Where a cost formula is decomposed into components, the rounding order is pinned: each component is rounded half-up to whole cents individually *before* the components are added together, and summing first and rounding once afterwards is a different, non-conformant result (the one exception is the provisional cost estimate, which is defined as a single rounding applied once at the end of the formula). Percentages reported to the regulator are rounded half-up to one decimal place. Hours are tracked in half-hour steps. Nurse counts are whole integers; per-level acuity division rounds up to a whole nurse before any summation. All staffing-threshold comparisons are exact integer comparisons — a boundary such as "at least" means greater-than-or-equal, and "at most" means less-than-or-equal, with no tolerance.

### 2.9. The Nursing Week, Shift Clock Times, and Overtime Accounting

Shifts come in exactly two codes. A `DAY` shift runs from 07:00 UTC on its `shift_date` to 19:00 UTC the same day; a `NIGHT` shift runs from 19:00 UTC on its `shift_date` to 07:00 UTC the following day. Both are twelve hours, so every assignment carries a `scheduled_hours` of 12.0 regardless of code. A shift's `start_at` and `end_at` are derived from its `shift_date` and `shift_code` at creation according to these clock times.

Weekly accounting follows the ISO week, running from Monday 00:00 UTC through Sunday. Two ledgers are maintained per nurse per week, and are readable through the nurse's week-ledger capability, which takes a `week_start` query parameter that must be a Monday and responds with the echoed `week_start` plus two figures: `projected_hours`, equal to 12.0 multiplied by the number of the nurse's assignments in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` status whose `shift_date` falls inside that week, and `completed_hours`, the sum of `actual_hours_worked` over the nurse's `COMPLETED` assignments in that week. Creating an assignment and then declining or cancelling that same assignment leaves `projected_hours` unchanged — the twelve hours enter on creation and leave on release.

The overtime regime is the same everywhere in the system: hours up to a weekly threshold of 40 are paid at the straight rate, and hours beyond 40 attract an overtime multiplier of one-and-a-half. How those hours are counted differs between the forward-looking estimate at assignment creation and the settled calculation at completion, and both are specified in §3.4 and §3.8 respectively.

### 2.10. The Unit Incentive Budget Ledger

Each nursing unit carries a premium-pay budget, `incentive_budget_cents`, against which two computed ledger accounts are maintained. `incentive_reserved_cents` is the sum of `premium_reserve_cents` over all of the unit's incentive offers currently in `OFFERED` or `CLAIMED` status; `incentive_spent_cents` is the sum of `premium_reserve_cents` over the unit's offers in `SETTLED` status. Both accounts start at zero when the unit is created.

The ledger obeys one conservation invariant: the unencumbered remainder — budget minus reserved minus spent — changes only when money is actually spent, that is, when an offer settles. A create-then-withdraw pair and a create-then-expire pair each leave both accounts exactly where they started, because the reservation taken at creation is released in full. Withdrawal and expiry subtract the reserve from `incentive_reserved_cents`; settlement subtracts it from `incentive_reserved_cents` and adds the same amount to `incentive_spent_cents`. New offers are gated against this ledger: the reserve the new offer would take, added to the current `incentive_reserved_cents`, must not exceed `incentive_budget_cents`, or creation fails with `ERR_INCENTIVE_BUDGET_EXCEEDED` (HTTP 402).

### 2.11. Scheduling Overlap: The Half-Open Interval Convention

A nurse may never hold two overlapping live commitments, where "live" means an assignment in `PROPOSED`, `ACCEPTED`, or `CONFIRMED` status. Overlap is decided on half-open intervals: an existing commitment overlaps a new one when the existing commitment's `start_at` is before the new commitment's `end_at` **and** the new commitment's `start_at` is before the existing commitment's `end_at`. Because the intervals are half-open, back-to-back shifts — where the new commitment starts exactly when the existing one ends — do **not** overlap and are allowed. The comparison is an exact datetime comparison. This convention governs direct assignment creation, incentive offer claims, and float candidate selection alike; violations surface as `ERR_SHIFT_OVERLAP` where a client-driven write is concerned, and as simple candidate exclusion inside the float selector.

## 3. Business Logic & Workflows

### 3.1. Configuring Units, Nurses, and the Staffing Matrix

Everything in the system hangs off three configuration aggregates owned by the `NurseAdmin`: units, nurses, and matrix rules.

A nursing unit is created with a human-readable `name` (for example, "4 West ICU"), a `unit_type` drawn from `ICU`, `STEP_DOWN`, `MED_SURG`, `TELEMETRY`, or `EMERGENCY`, a licensed `bed_count` that must be greater than zero, and the `incentive_budget_cents` for the staffing period, which may be zero but never negative. The optional `auto_incentive_multiplier`, when set to a value such as 1.5, arms the automatic incentive cascade described in §3.6; leaving it null disables that behavior for the unit. The unit's `incentive_reserved_cents` and `incentive_spent_cents` are computed ledger fields, initialized to zero at creation and maintained thereafter per §2.10.

A nurse profile records the `full_name`, an `employment_type` of `CORE` or `FLOAT_POOL`, a non-empty `competencies` array listing the `unit_type` values the nurse is validated to work, a `charge_qualified` flag that defaults to false when omitted, and a `base_hourly_rate_cents` that must be greater than zero. The `home_unit_id` obeys a conditional rule tied to employment type: a `CORE` nurse must be created with a `home_unit_id` pointing at their home unit, while a `FLOAT_POOL` nurse must have no home unit at all. Violating either half of that rule — a core nurse without a home unit, or a float-pool nurse with one — is rejected with `ERR_HOME_UNIT_RULE_VIOLATED`. Nurse records can be listed with optional filters on `home_unit_id` and `employment_type`.

The staffing matrix translates acuity into headcount. Each `StaffingMatrixRule` pairs a `unit_type` with an `acuity_level` — one of `LOW`, `MODERATE`, `HIGH`, or `CRITICAL` — and declares the `patients_per_nurse`, the maximum number of patients one nurse may carry at that acuity on that unit type, which must be at least 1. The (unit type, acuity level) pair is unique across the matrix: a second rule for the same pair is rejected with `ERR_MATRIX_RULE_EXISTS`. A complete matrix for a unit type therefore consists of exactly four rules, one per acuity level, and §3.2 shows what happens when a snapshot arrives before all four exist.

### 3.2. Census Capture and the Acuity Cascade

Twice per staffed slot, reality is re-measured. A `ChargeNurse` submits an `AcuitySnapshot` for a slot identified by `unit_id`, `shift_date` (an ISO date), and `shift_code`, carrying the four census counts: `census_low`, `census_moderate`, `census_high`, and `census_critical`, each of which must be zero or greater. Submission is only possible once all four staffing matrix rules exist for the unit's `unit_type`; if any of the four is missing, the submission is rejected with `ERR_MATRIX_RULE_MISSING` (HTTP 422).

A snapshot enters directly in `SUBMITTED` status — there is no draft phase. From its census counts the system derives `total_census`, the plain sum of the four census fields, and `required_nurses`, computed as follows. For each acuity level, the census at that level is divided by the `patients_per_nurse` of the matrix rule for this unit's type at that level, and the quotient is rounded up to a whole nurse; a level with zero patients contributes zero. The four per-level figures are then summed, and `required_nurses` is the greater of two and that sum — every slot demands at least two nurses no matter how light the census. The per-level rounding-up happens before the summation, and that order is pinned.

Only one snapshot governs a slot at a time. When a new snapshot is submitted for a slot that already has a `SUBMITTED` snapshot, the previous one transitions to `SUPERSEDED`, and the supersede fires a cascade into the matching shift, if one exists. The shift's `governing_snapshot_id` is re-pointed at the new snapshot — it always references the latest non-`SUPERSEDED` snapshot for its (unit, date, code) — the shift's `required_nurses` is recomputed from the new snapshot, the shift's `version` increments by one, and its staffing posture is re-evaluated with the `OPEN`-to-`STAFFED` reconciliation of §2.7 applied.

One further branch fires off the supersede cascade. If the recomputed posture is `CRITICAL` and the shift has no float request currently `DEPLOYED`, the system creates a float request with `origin` set to `AUTO_ACUITY` and immediately runs the candidate selection of §3.5 against it: a successful selection creates the proposed float assignment and marks the request `DEPLOYED`, while an empty candidate pool leaves the request `UNFULFILLED`. All of this happens synchronously within the snapshot submission. Snapshot history remains browsable — the snapshot list supports optional filters on `unit_id`, `shift_date`, `shift_code`, and `status` — so superseded censuses stay auditable even though only the governing one drives the shift.

### 3.3. Standing Up a Shift and Locking It

A `NurseAdmin` creates a shift for a unit by naming the slot — `unit_id`, `shift_date`, and `shift_code` — but creation is gated on measurement: a `SUBMITTED` acuity snapshot must already exist for exactly that slot, and its absence is rejected with `ERR_ACUITY_SNAPSHOT_REQUIRED` (HTTP 422). The slot is unique: a second shift for the same (unit, date, code) triple is rejected with `ERR_SHIFT_ALREADY_EXISTS`. At creation the shift copies its `required_nurses` from the governing snapshot, derives `start_at` and `end_at` from the clock times of §2.9, evaluates its posture — which, with zero assignments on the books, is necessarily `CRITICAL` — and opens in `OPEN` status.

From then until lock, the shift is a recomputation surface. `counted_assignments` tracks how many assignments sit in `ACCEPTED` or `CONFIRMED`; `sitter_diversion_count` tracks how many `FILLED` sitter requests are covered by assignments of this shift; `effective_assignments` is the first figure minus the second; and `charge_covered` is true exactly when an `ACCEPTED` or `CONFIRMED` assignment with `is_charge` set exists. The posture evaluation, re-run after every mutation of those inputs, is: `ADEQUATE` when effective assignments are at least `required_nurses` and, additionally, either `required_nurses` is less than two or charge coverage exists; otherwise `UNDERSTAFFED` when effective assignments are at least `required_nurses` minus one; and `CRITICAL` when effective assignments are less than or equal to `required_nurses` minus two. The shift list endpoint exposes this surface with optional filters on `unit_id`, `shift_date`, `shift_code`, `status`, `staffing_posture`, and `governing_snapshot_id`.

Locking is the `ChargeNurse`'s end-of-planning act and is permitted from either `OPEN` or `STAFFED`; attempting it on an already-locked shift is rejected with `ERR_SHIFT_NOT_OPEN`. The lock freezes `posture_at_lock` and `counted_at_lock` from their live values and stops all further posture recomputation — the frozen pair, not the live fields, is what compliance reporting later consumes. The lock cascade then resolves everything pending: each `PROPOSED` assignment on the shift transitions to `CANCELLED` with its projected twelve hours released back to the nurse's week, and any float request still `DEPLOYED` behind such an assignment transitions to `RELEASED`; every `OFFERED` incentive offer on the shift transitions to `EXPIRED` with its budget reserve released per §2.10. Assignments already `ACCEPTED` or `CONFIRMED` are retained untouched — locking never strands confirmed staff.

### 3.4. Direct Assignment: Proposal, Response, and Confirmation

The bread-and-butter staffing action is a `ChargeNurse` proposing a direct assignment onto a shift. The proposal payload names the `nurse_id`, may set `is_charge` to designate the shift's charge nurse (defaulting to false when omitted), and must carry the concurrency token `expected_shift_version` described in §2.6 — a token that does not match the shift's current `version` fails the create with `ERR_STALE_SHIFT_VERSION` after the state checks have run. Three safety rules guard the proposal: the nurse's `competencies` must include the shift's unit type, else `ERR_COMPETENCY_NOT_HELD`; a request to set `is_charge` on a nurse whose `charge_qualified` is false fails with `ERR_NOT_CHARGE_QUALIFIED`; and the new commitment must not overlap any of the nurse's live commitments under the half-open rule of §2.11, else `ERR_SHIFT_OVERLAP`.

A successfully created assignment enters in `PROPOSED` status with `source` set to `DIRECT`, `premium_multiplier` at 1.0, and `flat_bonus_cents` at 0. Creation increments the shift's `version` by one and adds twelve hours to the nurse's projected week, but a proposal does **not** move `counted_assignments` — only accepted and confirmed work counts toward posture. Creation also stamps the forward-looking economics: `projected_ot_hours` and `provisional_cost_cents` are computed from the nurse's week as it stands at that moment. Prior hours are taken as the sum of `actual_hours_worked` over the nurse's `COMPLETED` assignments in the shift's ISO week plus 12.0 for each of the nurse's `PROPOSED`, `ACCEPTED`, and `CONFIRMED` assignments in that week. The projected overtime is the smaller of 12.0 and the greater of zero and (prior hours plus 12.0 minus the 40-hour weekly threshold). The provisional cost is then the straight-time portion — 12.0 minus the projected overtime hours — multiplied by the nurse's `base_hourly_rate_cents` and the assignment's `premium_multiplier`, plus the projected overtime hours multiplied by the base rate, the premium multiplier, and the one-and-a-half overtime factor, plus any `flat_bonus_cents`; the whole total is rounded half-up to whole cents in a single rounding step at the end.

The response loop belongs to the nurse. A `StaffNurse` acting as themselves — `X-User-ID` equal to the assignment's `nurse_id`, else `ERR_NOT_RESOURCE_OWNER` — may accept or decline a `PROPOSED` assignment; calling either on an assignment in any other non-terminal state fails with `ERR_ASSIGNMENT_NOT_PROPOSED`, and calling either on a terminal assignment (`COMPLETED`, `DECLINED`, or `CANCELLED`) fails with `ERR_ASSIGNMENT_TERMINAL`. Acceptance moves the assignment to `ACCEPTED`, adds one to the shift's `counted_assignments`, and triggers the posture re-evaluation with its `OPEN`-and-`STAFFED` reconciliation. Declining moves it to `DECLINED`, releases the twelve projected hours, and — when the assignment's `source` is `FLOAT` — returns the parent float request, if still `DEPLOYED`, to `UNFULFILLED`.

Confirmation is a second, deliberate gate by the `ChargeNurse`, moving `ACCEPTED` to `CONFIRMED`; it requires the assignment to be `ACCEPTED` (else `ERR_ASSIGNMENT_NOT_ACCEPTED`) and the shift to be unlocked (`OPEN` or `STAFFED`, else `ERR_SHIFT_NOT_OPEN`). Two further gates are evaluated at confirm time. The charge-slot gate: if the assignment carries `is_charge`, no other `ACCEPTED` or `CONFIRMED` assignment on the same shift may already hold the charge designation, else `ERR_CHARGE_SLOT_TAKEN`. The skill-mix gate: after this confirmation, the number of the shift's counted assignments held by `FLOAT_POOL` nurses must not exceed half of the shift's counted assignments rounded down to a whole number, else `ERR_SKILL_MIX_VIOLATION`. Confirmation re-evaluates posture. A confirmation may also be walked back: revoking a confirmation returns the assignment from `CONFIRMED` to `ACCEPTED` — requiring it to be `CONFIRMED` (else `ERR_ASSIGNMENT_NOT_CONFIRMED`) and the shift unlocked — and since `ACCEPTED` still counts toward staffing, the posture re-evaluation runs again on the unchanged numerator.

Cancellation by a `ChargeNurse` is available for any assignment not yet terminal — targeting a `COMPLETED`, `DECLINED`, or `CANCELLED` assignment fails with `ERR_ASSIGNMENT_TERMINAL` — provided the assignment is not currently covering a `FILLED` sitter request, which fails with `ERR_COVERS_ACTIVE_SITTER`. Cancelling from `PROPOSED` releases the twelve projected hours and, if the source is `FLOAT` and the parent float request is still `DEPLOYED`, releases that request to `RELEASED`. Cancelling from `ACCEPTED` or `CONFIRMED` does more: the twelve projected hours are released, `counted_assignments` drops by one, posture is re-evaluated, and an incentive-funded assignment (source `INCENTIVE`) whose offer is `CLAIMED` withdraws that offer with its reserve released. When such a confirmed-staff loss flips the shift's posture from `ADEQUATE` down to `UNDERSTAFFED` or `CRITICAL`, the unit's automatic-incentive arm of §3.6 may fire. All assignments remain queryable through the assignment list with optional filters on `shift_id`, `nurse_id`, `status`, and `source`.

### 3.5. Float Pool Deployment

When a shift cannot be covered from its own roster, a `FloatCoordinator` requests a float deployment by supplying the `shift_id`; the system also creates such requests itself with `origin` `AUTO_ACUITY` during the cascade of §3.2, in which case the `shift_id` is system-supplied. Either way, deployment is attempted synchronously at creation — there is no pending state for a float request. A coordinator-created request has `origin` `MANUAL`.

Candidate selection is deterministic and runs over every `FLOAT_POOL` nurse. A candidate must hold the shift's unit type among their `competencies`, must have no live assignment (`PROPOSED`, `ACCEPTED`, or `CONFIRMED`) whose shift interval overlaps the target shift under the half-open rule of §2.11 — touching endpoints are not overlaps — and must have headroom in the week: their `projected_hours` for the shift's ISO week, after adding the twelve hours this shift would contribute, must not exceed 60. Eligible candidates are ranked by their projected hours for the shift's week, ascending, and ties are broken by the nurse's `created_at` timestamp, ascending — never by identifier. The winner receives a new assignment in `PROPOSED` status with `source` `FLOAT` — created on straight-time terms, with `premium_multiplier` at 1.0 and `flat_bonus_cents` at 0 — and the float request enters `DEPLOYED` with `deployed_nurse_id` and `assignment_id` recording the outcome. An empty candidate pool leaves the request `UNFULFILLED` and creates no assignment. Float requests remain listable with optional filters on `shift_id`, `deployed_nurse_id`, `assignment_id`, and `status`.

A deployed float can be handed back to the pool by the `FloatCoordinator`, but only while the deployment is still tentative: the request must be `DEPLOYED` and its linked assignment still `PROPOSED`. Once the nurse has accepted, or the request is in any other state, release is rejected with `ERR_FLOAT_REQUEST_NOT_RELEASABLE`. A successful release transitions the request to `RELEASED`, cancels the linked proposed assignment with its projected-hours release, and re-evaluates the shift's posture. The same release happens automatically when the linked assignment is cancelled or the shift is locked.

### 3.6. Premium Incentive Offers

Premium pay is the budgeted lever of last resort. A `NurseAdmin` creates an incentive offer against a shift by supplying the `shift_id`, a `premium_multiplier` that must be greater than 1.0 and no more than 3.0, and an optional `flat_bonus_cents` that defaults to zero and may never be negative. Offers are only lawful while the shift is short: creating one while the shift's posture is `ADEQUATE` is rejected with `ERR_SHIFT_ADEQUATELY_STAFFED` — only `UNDERSTAFFED` or `CRITICAL` postures qualify. At most one offer per shift may be open at a time; a second creation while an `OFFERED` offer exists fails with `ERR_OFFER_ALREADY_ACTIVE`. These manually created offers carry `origin` `MANUAL`.

Every offer takes a budget reserve at creation, computed as the `flat_bonus_cents` plus the premium portion of a twelve-hour shift at a reference rate of 6,000 cents per hour — that is, twelve times 6,000 multiplied by the amount by which the `premium_multiplier` exceeds 1.0, rounded half-up to whole cents. This `premium_reserve_cents` is added to the unit's `incentive_reserved_cents` at creation, and the fiscal gate of §2.10 applies: if the reserve would push reserved funds past `incentive_budget_cents`, creation fails with `ERR_INCENTIVE_BUDGET_EXCEEDED`.

The system can also open offers on its own. When a unit has `auto_incentive_multiplier` set and a confirmed-staff cancellation flips a shift's posture from `ADEQUATE` to `UNDERSTAFFED` or `CRITICAL`, an offer with `origin` `AUTO` is created using that multiplier and a zero flat bonus — but only if no `OFFERED` offer already exists for the shift and only if the reserve fits within the unit's remaining budget; if the budget check fails, the automatic offer is silently skipped rather than surfaced as an error.

A `StaffNurse` claims an open offer, which requires the offer to be `OFFERED` (else `ERR_OFFER_INVALID_STATE`), the nurse's `competencies` to include the shift's unit type (else `ERR_COMPETENCY_NOT_HELD`), and no overlap against the nurse's live assignments under the half-open rule (else `ERR_SHIFT_OVERLAP`). Claiming creates an assignment that enters directly in `ACCEPTED` status with `source` `INCENTIVE`, its `premium_multiplier` and `flat_bonus_cents` copied from the offer; the offer moves to `CLAIMED` with `claimed_nurse_id` and `claimed_assignment_id` recorded, and the shift's `counted_assignments` rises by one with the usual posture re-evaluation. Because claiming creates the assignment, the provisional economics of §3.4 are stamped at that moment using the premium terms.

An unclaimed offer can be pulled by a `NurseAdmin`: withdrawal requires `OFFERED` (else `ERR_OFFER_INVALID_STATE`) and moves the offer to `WITHDRAWN` with its reserve subtracted from the unit's `incentive_reserved_cents`. Offers that are still `OFFERED` when their shift locks transition to `EXPIRED` with the same reserve release. A `CLAIMED` offer resolves with its assignment: completion of the claimed assignment settles the offer to `SETTLED`, moving the reserve from reserved to spent on the unit's ledger, while cancellation of the claimed assignment withdraws the offer with the reserve released. Offers are listable with optional filters on `shift_id`, `claimed_nurse_id`, `claimed_assignment_id`, and `status`.

### 3.7. Sitter Coverage and Observation Windows

Some patients require continuous one-to-one observation, and the staff for it come out of the unit's own confirmed roster. A `ChargeNurse` opens a sitter request with the `unit_id`, a de-identified `patient_ref`, and an observation window from `start_at` to `end_at` — both ISO 8601 UTC instants, with `end_at` strictly after `start_at` or the request shape check rejects it. The request enters in `PENDING` status.

Filling the request, again a `ChargeNurse` act, requires the request to be `PENDING` (else `ERR_SITTER_INVALID_STATE`) and names the `nurse_id` who will sit. That nurse must hold a `CONFIRMED` assignment on the same unit whose shift interval fully contains the observation window — the shift's `start_at` at or before the window's start and the shift's `end_at` at or after the window's end — and that assignment must not already be covering another `FILLED` sitter request; failing either condition yields `ERR_NO_COVERING_ASSIGNMENT`. A successful fill records `assigned_nurse_id` and `covering_assignment_id` on the now-`FILLED` request, increments the covering shift's `sitter_diversion_count` by one, and re-evaluates posture — note that diversion reduces `effective_assignments`, so filling a sitter can by itself push a shift from `ADEQUATE` to `UNDERSTAFFED` or `CRITICAL`.

Releasing a filled request, permitted only from `FILLED` (else `ERR_SITTER_INVALID_STATE`), moves it to `RELEASED`, decrements the covering shift's `sitter_diversion_count`, and re-evaluates posture again. The active-sitter lock runs the other direction as well: an assignment that currently covers a `FILLED` sitter request cannot be cancelled or completed — both attempts fail with `ERR_COVERS_ACTIVE_SITTER` — until the sitter is released. Sitter requests are listable with optional filters on `unit_id`, `assigned_nurse_id`, `covering_assignment_id`, and `status`.

### 3.8. Completing Assignments: Actuals, Overtime, and Final Cost

After the work is done, a `ChargeNurse` completes a `CONFIRMED` assignment — any other state fails with `ERR_ASSIGNMENT_NOT_CONFIRMED`, and the active-sitter lock of §3.7 applies — by reporting `actual_hours_worked`, which must be greater than zero and no more than 16, and `missed_breaks`, which must be zero or greater. Completion moves the assignment to `COMPLETED`, releases the twelve projected hours from the nurse's week, adds the actual hours to the nurse's completed weekly total, and settles the money.

The settled cost replaces the estimate with actuals and uses chronological, completion-order overtime accounting. Running hours are the sum of `actual_hours_worked` over the nurse's assignments already in `COMPLETED` status in the same ISO week, evaluated at the moment this completion is recorded — completion order determines which assignments are in that sum, and earlier completions are never retroactively adjusted. The `final_ot_hours` are the smaller of `actual_hours_worked` and the greater of zero and (running hours plus `actual_hours_worked` minus the 40-hour weekly threshold); the remaining non-overtime portion is `actual_hours_worked` minus `final_ot_hours`. The normal-pay component is that non-overtime portion multiplied by `base_hourly_rate_cents` and `premium_multiplier`, rounded half-up to whole cents; the overtime component is `final_ot_hours` multiplied by the base rate, the premium multiplier, and the one-and-a-half factor, also rounded half-up to whole cents on its own. Per §2.8, the two components are rounded individually before being added — summing first and rounding once afterwards is non-conformant. The recorded `final_cost_cents` is the sum of the two rounded components, plus 5,000 cents for each entry in `missed_breaks`, plus any `flat_bonus_cents`. If the completed assignment's `source` is `INCENTIVE` and its offer is `CLAIMED`, the offer settles per §3.6, moving the reserve from the unit's reserved account into its spent account.

### 3.9. Staffing-Plan Compliance Reporting

The reporting loop closes with the regulator. A `NurseAdmin` creates a `ComplianceReport` for a `report_date`; one report per date is the rule, and a duplicate date is rejected with `ERR_REPORT_ALREADY_EXISTS`. The report enters in `DRAFT`, holding no computed figures yet.

Submission — from `DRAFT`, or again from `RETURNED` in the revision loop; any other state fails with `ERR_REPORT_INVALID_STATE` — is gated on finality. At least one shift must exist with a `shift_date` equal to the `report_date` (else `ERR_NO_SHIFTS_FOR_REPORT_DATE`, HTTP 422), and every shift for that date must be `LOCKED` (else `ERR_SHIFTS_NOT_LOCKED`). On submission the report's four figures are computed, and recomputed identically on every resubmission. `shifts_included_count` counts the `LOCKED` shifts whose `shift_date` equals the report date. For each included shift, a fill ratio is taken as the smaller of one and the quotient of the shift's frozen `counted_at_lock` divided by its `required_nurses`. `fill_rate_shift_weighted_pct` is one hundred times the plain average of those ratios across included shifts — every shift weighing equally — rounded half-up to one decimal place. `fill_rate_census_weighted_pct` weights each shift's ratio by the `total_census` of the shift's governing snapshot: one hundred times the sum of each ratio multiplied by its census, divided by the sum of all censuses, again rounded half-up to one decimal place; high-census shifts dominate this variant, and if the summed census is zero the census-weighted figure falls back to the shift-weighted figure. `understaffed_shift_count` counts the included shifts whose frozen `counted_at_lock` is strictly less than `required_nurses`.

The `Regulator` then adjudicates a `SUBMITTED` report — acting on a report in any other state fails with `ERR_REPORT_INVALID_STATE`. Returning the report moves it to `RETURNED` and records the regulator's optional `return_reason`; accepting it moves it to `ACCEPTED`, which is terminal. A returned report re-enters the loop: the `NurseAdmin` resubmits, all four figures are recomputed against whatever the frozen shift data then shows, and the regulator reviews again.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Successful responses return the created or updated resource in the envelope's `data` field per §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/units` | Create a nursing unit | NurseAdmin |
| GET | `/units/{unitId}` | Get a nursing unit | All roles |
| POST | `/nurses` | Create a nurse profile | NurseAdmin |
| GET | `/nurses` | List nurses | All roles |
| GET | `/nurses/{nurseId}` | Get a nurse | All roles |
| GET | `/nurses/{nurseId}/week-ledger` | Computed weekly hours ledger for the ISO week containing `week_start` | All roles |
| POST | `/matrix-rules` | Create a staffing matrix rule | NurseAdmin |
| POST | `/acuity-snapshots` | Submit a census/acuity snapshot (supersedes the prior snapshot and runs the shift recompute cascade) | ChargeNurse |
| GET | `/acuity-snapshots` | List acuity snapshots | All roles |
| GET | `/acuity-snapshots/{snapshotId}` | Get an acuity snapshot | All roles |
| POST | `/shifts` | Create a shift slot for a unit (requires a submitted snapshot for the slot) | NurseAdmin |
| GET | `/shifts` | List shifts | All roles |
| GET | `/shifts/{shiftId}` | Get a shift | All roles |
| POST | `/shifts/{shiftId}/lock` | Lock the shift (freezes posture and counts, cancels proposed assignments, expires open offers) | ChargeNurse |
| POST | `/shifts/{shiftId}/assignments` | Charge nurse proposes a direct assignment (OCC-guarded) | ChargeNurse |
| GET | `/assignments` | List assignments | All roles |
| GET | `/assignments/{assignmentId}` | Get an assignment | All roles |
| POST | `/assignments/{assignmentId}/accept` | Nurse accepts own proposed assignment | StaffNurse |
| POST | `/assignments/{assignmentId}/decline` | Nurse declines own proposed assignment | StaffNurse |
| POST | `/assignments/{assignmentId}/confirm` | Charge nurse confirms an accepted assignment (skill-mix and charge-slot gates) | ChargeNurse |
| POST | `/assignments/{assignmentId}/revoke-confirmation` | Charge nurse revokes a confirmation | ChargeNurse |
| POST | `/assignments/{assignmentId}/cancel` | Charge nurse cancels a non-terminal assignment | ChargeNurse |
| POST | `/assignments/{assignmentId}/complete` | Record actuals and complete a confirmed assignment | ChargeNurse |
| POST | `/float-requests` | Request float pool deployment to a shift; selector runs synchronously | FloatCoordinator |
| GET | `/float-requests` | List float requests | All roles |
| GET | `/float-requests/{floatRequestId}` | Get a float request | All roles |
| POST | `/float-requests/{floatRequestId}/release` | Release a deployed float nurse back to the pool | FloatCoordinator |
| POST | `/incentive-offers` | Create a premium incentive offer for an understaffed shift | NurseAdmin |
| GET | `/incentive-offers` | List incentive offers | All roles |
| GET | `/incentive-offers/{offerId}` | Get an incentive offer | All roles |
| POST | `/incentive-offers/{offerId}/claim` | Nurse claims an open premium offer | StaffNurse |
| POST | `/incentive-offers/{offerId}/withdraw` | Withdraw an unclaimed offer and release its reserve | NurseAdmin |
| POST | `/sitter-requests` | Create a one-to-one observation (sitter) request | ChargeNurse |
| GET | `/sitter-requests` | List sitter requests | All roles |
| GET | `/sitter-requests/{sitterRequestId}` | Get a sitter request | All roles |
| POST | `/sitter-requests/{sitterRequestId}/fill` | Fill a sitter request with a nurse holding a covering confirmed assignment | ChargeNurse |
| POST | `/sitter-requests/{sitterRequestId}/release` | Release a filled sitter request | ChargeNurse |
| POST | `/compliance-reports` | Create a staffing-plan compliance report for a date | NurseAdmin |
| GET | `/compliance-reports/{reportId}` | Get a compliance report | All roles |
| POST | `/compliance-reports/{reportId}/submit` | Submit (or resubmit after return) the report; computes both fill-rate variants | NurseAdmin |
| POST | `/compliance-reports/{reportId}/return` | Regulator returns a submitted report for revision | Regulator |
| POST | `/compliance-reports/{reportId}/accept` | Regulator accepts a submitted report (terminal) | Regulator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_NURSE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIFT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_OFFER_NOT_FOUND` | 404 Not Found |
| `ERR_FLOAT_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_SITTER_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_HOME_UNIT_RULE_VIOLATED` | 400 Bad Request |
| `ERR_SHIFT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_MATRIX_RULE_EXISTS` | 409 Conflict |
| `ERR_OFFER_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_REPORT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_MATRIX_RULE_MISSING` | 422 Unprocessable Entity |
| `ERR_ACUITY_SNAPSHOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_SHIFTS_FOR_REPORT_DATE` | 422 Unprocessable Entity |
| `ERR_SHIFT_NOT_OPEN` | 409 Conflict |
| `ERR_STALE_SHIFT_VERSION` | 412 Precondition Failed |
| `ERR_ASSIGNMENT_NOT_PROPOSED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_ASSIGNMENT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ASSIGNMENT_TERMINAL` | 409 Conflict |
| `ERR_COMPETENCY_NOT_HELD` | 409 Conflict |
| `ERR_NOT_CHARGE_QUALIFIED` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_CHARGE_SLOT_TAKEN` | 409 Conflict |
| `ERR_SKILL_MIX_VIOLATION` | 409 Conflict |
| `ERR_NO_COVERING_ASSIGNMENT` | 409 Conflict |
| `ERR_COVERS_ACTIVE_SITTER` | 409 Conflict |
| `ERR_SITTER_INVALID_STATE` | 409 Conflict |
| `ERR_OFFER_INVALID_STATE` | 409 Conflict |
| `ERR_SHIFT_ADEQUATELY_STAFFED` | 409 Conflict |
| `ERR_INCENTIVE_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_FLOAT_REQUEST_NOT_RELEASABLE` | 409 Conflict |
| `ERR_REPORT_INVALID_STATE` | 409 Conflict |
| `ERR_SHIFTS_NOT_LOCKED` | 409 Conflict |
