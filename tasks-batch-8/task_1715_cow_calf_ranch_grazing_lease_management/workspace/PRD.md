# Cow-Calf Grazing API — Product Requirements Document

## 1. Introduction

A western cow-calf outfit runs on a small set of tightly coupled decisions: how many head a pasture can carry through a five-month grazing season, which bulls are sound enough to turn out, whether the calf crop has earned a preconditioning premium at sale time, and how fast the ranch must destock when forage runs short. In most operations these decisions live in notebooks and spreadsheets, which makes it nearly impossible to answer the questions that actually cost money — how many Animal Unit Months remain uncommitted on a given pasture, whether a grazing lease should be settled on its contracted allotment or on measured use, or which herd groups a drought order should pull head from first.

This document specifies the Cow-Calf Grazing API, a system that manages the ranch's breeding and calving program, pasture rotation and stocking-rate accounting, calf marketing with slide-and-premium settlement, grazing lease administration, mineral and supplement programs, herd genetics through the bull battery, drought contingency with formal destocking orders, and replacement heifer retention. All endpoints are mounted under the `/api` prefix. The API is built around an explicit forage ledger measured in Animal Unit Months (AUM), a logical clock against which every date is interpreted, and a segregation-of-duties model in which the people who record field data are never the people who approve the money.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` identifying the acting operator and `X-User-Role` naming the capacity in which they act. The system recognizes exactly four roles: `RanchManager`, the ranch owner or manager, who holds approval authority over lease statements, sale-lot settlements, drought policy, and destock-order waivers, but who may not record field data; `RangeManager`, the range and lease operator responsible for pastures, grazing leases, lease statements, grazing assignments, and drought assessments; `HerdManager`, the cow boss responsible for herd groups, breeding seasons, bulls and their turnouts, pregnancy checks, calf crops, and supplement programs; and `SalesAgent`, the calf marketing agent who runs sale lots from creation through delivery and dispute but can never settle a lot.

A request whose headers are missing, or whose `X-User-Role` does not name one of the four declared roles, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Every read endpoint in the system is open to all four roles; write capabilities are role-specific as enumerated in §4.

For all four roles — `RanchManager`, `RangeManager`, `HerdManager`, and `SalesAgent` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources as an attribution anchor — `recorded_by_user_id` on a lease statement, `sold_by_user_id` on a sale lot, `approved_by_user_id` on an approved statement, and `settled_by_user_id` on a settled lot — and compares those recorded identities against a later caller's `X-User-ID` only for the segregation-of-duties checks described in §2.10. It is never compared to any entity's `id`.

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

List endpoints accept two query parameters that control the returned window of results. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip from the front of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order — the oldest resource first.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full size of the filtered result set and `has_more` indicates whether additional items remain beyond the returned window.

### 2.4. The Ranch Logical Clock

The system does not consult wall-clock time. A logical clock governs every date comparison in state machines, calculations, and validations; the phrase "current date" throughout this document means the UTC calendar date of that logical clock. A `RanchManager` advances the clock through a test-driving capability that accepts a `to_iso8601` timestamp and answers with the resulting `current_utc`. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time under any circumstance.

All domain date fields — lease windows, turnout dates, weaning dates, delivery dates, assessment dates — are ISO calendar dates in YYYY-MM-DD form and are interpreted against this clock. Several status derivations are deliberately lazy rather than job-driven: a bull's breeding-soundness expiry, a lease's expiry past its window, and a pasture's emergence from rest are all re-evaluated against the logical clock on the next read or mutation of the affected resource, never by a background sweep.

### 2.5. Common Resource Properties

Every primary resource in the system — ranches, pastures, grazing leases, lease statements, herd groups, breeding seasons, bulls, bull turnouts, pregnancy checks, calf crops, sale lots, grazing assignments, supplement programs, drought assessments, and destock orders — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the resource's last modification; it refreshes on any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource and anchors the optimistic concurrency controls of §2.7.

Every successful create or modify operation returns the affected resource object, with these fields populated, in the envelope's `data` field.

### 2.6. Units, Precision, and Rounding Discipline

Monetary amounts are denominated in cents and, wherever a computation produces a monetary result, that result is rounded half-up to exactly 2 decimal places. AUM quantities — reserved, consumed, committed, available, effective — are likewise carried at 2 decimal places with round-half-up. Percentages (forage production percentages, pregnancy rate) and the adjusted 205-day weaning weights are rounded half-up to 1 decimal place. The animal-unit factor is the finest-grained quantity in the system, rounded half-up to 4 decimal places. Head counts are always whole animals; wherever a division would produce a fractional head requirement, the count is rounded up to the next whole animal. One rounding convention applies everywhere: round half up, with no banker's rounding and no truncation.

Two unit conversions recur across the domain. One AUM is defined as one animal unit grazing for a 30-day month, so daily forage demand divides by 30 to yield AUM. Feed quantities move between ounces per head per day, pounds (16 ounces to the pound), and tons (2,000 pounds to the ton); the projections and cost accumulations in §3.3 state exactly where each conversion applies. All computed values are represented in API responses as standard JSON numbers, never as strings.

### 2.7. Optimistic Concurrency Control

Exactly two write operations in the system are guarded by optimistic concurrency control, and each names its guard field explicitly. Amending the terms of a grazing lease requires the request to carry `expected_lease_version`, holding the `version` of the lease the client last observed. Finalizing a drought assessment requires the request to carry `expected_ranch_version`, holding the `version` of the ranch the client last observed. Both fields are non-optional on their respective operations.

When the supplied expectation does not equal the parent resource's current `version` — because another write has advanced that version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). For a lease amendment this prevents a stale editor from overwriting terms it has not observed; for an assessment finalization it forces the caller to re-base on the freshest ranch state, since finalization supersedes the ranch's drought posture wholesale. No endpoint other than these two accepts a version-expectation field.

### 2.8. Validation Cascade and Nested Resource Retrieval

Every request is validated against an ordered cascade, and the first failing check determines the returned error — later checks are never evaluated once an earlier one has failed. The cascade runs in this order:

1. Context headers are present and name a declared role (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`).
2. The role is authorized for the target endpoint (`ERR_FORBIDDEN_ROLE`).
3. Segregation-of-duties comparisons, where the endpoint defines one (`ERR_SEGREGATION_OF_DUTIES`).
4. Existence: every identifier in the path is resolved, validated left-to-right, and every foreign-key identifier in the request body exists and belongs to the same ranch as the resource it is attached to (`ERR_NOT_FOUND`). A body reference that points at another ranch's resource is reported as not found, not as a permission failure.
5. Request-body well-formedness: required fields are present, enum members are valid, no computed, system-managed, or unknown fields are supplied, quantities are positive, and any window's start precedes its end (`ERR_INVALID_REQUEST`).
6. Generic transition validity: the requested transition exists from the resource's current, non-terminal state (`ERR_INVALID_STATE_TRANSITION`).
7. Terminal-state rejection: a resource that has reached a terminal state refuses all further transitions (`ERR_ALREADY_TERMINAL`). This same rejection covers creating a sale lot against a calf crop whose lifecycle has closed.
8. Specific state gates, each with its own error: the target pasture is not closed (`ERR_PASTURE_NOT_GRAZEABLE`), the covering lease is in an acceptable status (`ERR_LEASE_NOT_ACTIVE`), the breeding season is in gestation when a pregnancy check is created (`ERR_SEASON_NOT_IN_GESTATION`), the calf crop is weaned when a sale lot is created (`ERR_CROP_NOT_WEANED`), and the crop is enrolled when preconditioning certification is attempted (`ERR_PRECON_NOT_ENROLLED`).
9. Optimistic concurrency expectations, on the two guarded operations of §2.7 (`ERR_STALE_VERSION`).
10. Drought commitment gates on new grazing assignments, in their pinned sub-order — a blocking destock order first (`ERR_DESTOCK_ORDER_BLOCKING`), then the drought posture gate (`ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT`).
11. Bull battery sufficiency at the start of breeding (`ERR_BULL_BATTERY_INSUFFICIENT`).
12. Pasture temporal rules for a new grazing assignment, in pinned sub-order — half-open window overlap first (`ERR_PASTURE_WINDOW_OVERLAP`), then the rest-buffer rule (`ERR_PASTURE_REST_VIOLATION`).
13. Bull turnout temporal rules for a new turnout, in pinned sub-order — closed-interval overlap first (`ERR_BULL_TURNOUT_OVERLAP`), then the minimum turnaround gap (`ERR_BULL_TURNAROUND_TOO_SHORT`).
14. Window nesting — an assignment inside its covering lease window (`ERR_ASSIGNMENT_OUTSIDE_LEASE_WINDOW`), a turnout inside its season's planned window (`ERR_TURNOUT_OUTSIDE_SEASON_WINDOW`).
15. Aggregate lease capacity on activation or reinstatement (`ERR_LEASE_CAPACITY_EXCEEDED`).
16. The amendment floor on recorded usage when lease terms change (`ERR_ALLOTMENT_BELOW_RECORDED_USAGE`).
17. Uniqueness constraints — one pregnancy check per breeding season (`ERR_PREG_CHECK_ALREADY_EXISTS`), one lease statement per lease and calendar year (`ERR_DUPLICATE_STATEMENT_PERIOD`).
18. Accounting identities and bounds — pregnancy counts summing to exposure (`ERR_PREG_COUNT_MISMATCH`), exposure within the group's head count (`ERR_EXPOSURE_EXCEEDS_GROUP`), reductions within the group's head count (`ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD`), heifer retention within available head and into the correct class (`ERR_RETENTION_EXCEEDS_AVAILABLE`, `ERR_RETENTION_CLASS_MISMATCH`), vaccine round spacing (`ERR_VACCINE_SPACING_VIOLATION`), and complete assessment measurements (`ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE`).
19. The forage budget on a new grazing assignment (`ERR_AUM_BUDGET_EXCEEDED`).
20. Calf-crop marketing gates (`ERR_INSUFFICIENT_CROP_HEAD`, `ERR_PRECON_CLAIM_EXCEEDS_CROP`, `ERR_PRECON_VACCINE_INCOMPLETE`, `ERR_PRECON_DAYS_INSUFFICIENT`).

Because the hierarchy of resources here is flat, nested-path resolution is simple, but the left-to-right rule still applies: where a path carries an identifier, that identifier is resolved before any body reference is examined, and the first unresolvable identifier yields the `ERR_NOT_FOUND` response.

### 2.9. The Forage Ledger: Capacity, Commitments, and Rest

Every pasture is a forage account measured in Animal Unit Months. Its `base_capacity_aum` is the rated capacity of the pasture for a five-month grazing season under a `NORMAL` drought posture. The pasture's `effective_capacity_aum` scales that rating by the ranch's current drought posture: the full base capacity under `NORMAL`, 85 percent of it under `WATCH`, 70 percent under `ALERT`, and 50 percent under `CRITICAL`, with the product rounded half-up to 2 decimal places. This effective capacity is recomputed on every read and every mutation of the pasture, so a posture change is reflected immediately.

Against that capacity the ledger tracks two draws. `committed_aum` is the sum of `reserved_aum` over the pasture's assignments whose `assignment_status` is `ACTIVE` — forage promised but not yet grazed. `consumed_total_aum` is the sum of `consumed_aum` over assignments that ended `COMPLETED` or `SHORTENED` — forage already eaten. The pasture's `available_aum` is what remains: the effective capacity minus the committed total minus the consumed total. A new grazing reservation is permitted whenever its reserved amount is less than or equal to `available_aum` — an exact fit is allowed — and is refused with `ERR_AUM_BUDGET_EXCEEDED` only when the reservation strictly exceeds what remains.

Rest is the third leg of the ledger. When an assignment ends, the pasture's `resting_until` is set to the assignment's actual end date plus the pasture's `min_rest_days`, and until the current date reaches that day the pasture reads as `RESTING`. A pasture's `condition_status` is `CLOSED` when its `closed_flag` has been set, otherwise `RESTING` while the current date is earlier than `resting_until`, otherwise `GRAZEABLE`. `RESTING` is informational only — it never blocks a new assignment by itself; the mandatory spacing between grazing windows is enforced separately by the rest-buffer rule of §3.9. Only `CLOSED` blocks creation, with `ERR_PASTURE_NOT_GRAZEABLE`.

### 2.10. Operator Identity Recording and Segregation of Duties

Two financial hand-offs in the system are protected by segregation of duties, and both compare the acting operator's `X-User-ID` against an identity recorded at an earlier step. A lease statement is born with `recorded_by_user_id` stamped from the `RangeManager` who generated it; approval requires a `RanchManager` whose `X-User-ID` is different from that recorder, and the approval stamps `approved_by_user_id`. A sale lot is born with `sold_by_user_id` stamped from the `SalesAgent` who created it; settlement requires a `RanchManager` whose `X-User-ID` is different from that seller, and the settlement stamps `settled_by_user_id`. Either comparison failing rejects the request with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The general principle — the `RanchManager` approves but never originates field or sales records — is what the role model exists to protect.

### 2.11. Drought Posture as a Ranch-Wide Commitment Gate

A ranch carries a `drought_posture` of `NORMAL`, `WATCH`, `ALERT`, or `CRITICAL`. That posture is never edited directly; it is set only by finalizing a drought assessment, as described in §3.8. Posture has two system-wide effects. First, it scales every pasture's effective capacity per §2.9. Second, it gates new grazing commitments: while the ranch's posture is `ALERT` or `CRITICAL`, any attempt to create a grazing assignment is rejected with `ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT` (HTTP 422).

Independently of posture, an unresolved destock order gates commitments harder. While any destock order on the ranch is `OPEN` or `EXPIRED`, creating a grazing assignment is rejected with `ERR_DESTOCK_ORDER_BLOCKING` (HTTP 422). When both gates could fire, the destock-order check is evaluated first, so a ranch under an open order always surfaces `ERR_DESTOCK_ORDER_BLOCKING` rather than the posture error. Both gates apply only to new grazing assignments; they do not block completing, shortening, or cancelling grazing that is already on the ground.

## 3. Business Logic & Workflows

### 3.1. Ranch Setup and the Pasture Inventory

Everything begins with the ranch. A `RanchManager` registers the operation with a display `name` and the two-letter `hq_state` of its headquarters, and may optionally set `destock_grace_days`, the number of days the outfit has to comply with a future destock order measured from the assessment that created it; when omitted, the grace period defaults to 30 days. A new ranch starts with `drought_posture` of `NORMAL`, a `ranch_production_pct` of 100.0, and an `assessment_seq` of zero — a counter that increments once for every drought assessment the ranch finalizes. The `RanchManager` may later update the `name`, `hq_state`, or `destock_grace_days` policy fields; each such update increments the ranch's `version`.

With the ranch established, a `RangeManager` builds the pasture inventory. Each pasture is registered under its `ranch_id` with a `name`, its grazeable `acreage`, a `tenure` of `DEEDED` or `LEASED`, a `forage_type` of `NATIVE_RANGE`, `IMPROVED`, or `CROP_RESIDUE`, and its rated `base_capacity_aum`. The mandatory recovery interval between grazing windows, `min_rest_days`, defaults to 45 days when not supplied. A fresh pasture is `GRAZEABLE` with nothing committed, nothing consumed, `closed_flag` false, and `resting_until` null because it has never been grazed. Reading a pasture always reflects the present: `condition_status`, `effective_capacity_aum`, `committed_aum`, `consumed_total_aum`, and `available_aum` are recomputed against the current posture and logical clock at read time.

Closing a pasture is a one-way door. A `RangeManager` may close a pasture only while no assignment with `assignment_status` of `ACTIVE` remains on it; closing sets `closed_flag` to true, moves the pasture to `CLOSED`, and is irreversible. Closed pastures drop out of drought measurement entirely — a drought assessment's pasture measurements must cover every pasture of the ranch that is not closed, and closed ground is excluded from both the production weighting and the supply side of the deficit math in §3.8.

### 3.2. Grazing Leases and Lease Settlement Statements

Leased ground carries the ranch's contractual obligations. A `RangeManager` drafts a grazing lease against a pasture whose tenure is `LEASED` — a lease may never be written against deeded ground — supplying the `ranch_id`, the `pasture_id`, the landowner's `lessor_name`, an inclusive lease window from `start_date` through `end_date`, the contracted `aum_allotment`, the `rate_per_aum_cents`, the take-or-pay floor `minimum_commit_aum`, the two overage tiers `overage_tier1_cap_aum` with `overage_tier1_rate_cents` and `overage_tier2_rate_cents`, and the `settlement_basis` of `ALLOTMENT` or `ACTUAL_USE`. The lease's `lease_status` is born `DRAFT`.

Activation is the moment contractual capacity is committed. A `RangeManager` activates a draft lease only while the pasture's tenure is `LEASED` and the pasture is not `CLOSED`, and only while the aggregate allotment discipline holds: the sum of `aum_allotment` over all `ACTIVE` leases on that pasture, the candidate included, must not exceed the pasture's `base_capacity_aum`, or the activation fails with `ERR_LEASE_CAPACITY_EXCEEDED` (HTTP 422). Lease windows may overlap on the same pasture — the discipline is aggregate capacity, not calendar exclusivity. An `ACTIVE` lease may be suspended, moving to `SUSPENDED` with no further preconditions, and a suspended lease may be reinstated to `ACTIVE`, which re-runs the same aggregate-capacity check against whatever commitments exist at that moment; the suspend–reinstate cycle is unrestricted in count. Every activation, suspension, reinstatement, and termination increments the lease's `version`.

Expiry is lazy: when the current date passes a lease's `end_date`, an `ACTIVE` lease reads as `EXPIRED` on the next read or mutation, with no operator action required. Termination is the hard stop and belongs to the `RanchManager` alone: a lease in `DRAFT`, `ACTIVE`, or `SUSPENDED` moves to `TERMINATED`, but termination is refused while any statement for the lease still sits in `DRAFT` or `ISSUED` — unsettled paperwork must be pushed through or cleared first.

Terms may be amended while a lease is `DRAFT`, `ACTIVE`, or `SUSPENDED`. Because both an amendment and any other write can legitimately advance the lease between a client's read and its write, the amendment call is one of the two OCC-guarded operations in the system: it must carry `expected_lease_version` equal to the lease's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.7. Any of `aum_allotment`, `rate_per_aum_cents`, `minimum_commit_aum`, `overage_tier1_cap_aum`, `overage_tier1_rate_cents`, `overage_tier2_rate_cents`, `settlement_basis`, `start_date`, or `end_date` may change, subject to one floor: the new `aum_allotment` may not fall below the largest `actual_aum_used` recorded on any non-draft statement of the lease, or the amendment is rejected with `ERR_ALLOTMENT_BELOW_RECORDED_USAGE` (HTTP 422). A successful amendment increments the lease's `version`.

Settlement runs on calendar years. A `RangeManager` generates a lease statement by naming the `lease_id`, the `ranch_id` (which must equal the lease's own ranch), and a `period_year` that must fall within the calendar years spanned by the lease — from the year of its `start_date` through the year of its `end_date` inclusive; a year outside that span is rejected as an `ERR_INVALID_REQUEST`. The lease must be in a settleable status: `ACTIVE`, `SUSPENDED`, or `EXPIRED` all accept statement generation, while a lease still in `DRAFT` or already `TERMINATED` rejects it with `ERR_LEASE_NOT_ACTIVE`. One statement may exist per lease per calendar year; a second attempt for the same pairing fails with `ERR_DUPLICATE_STATEMENT_PERIOD` (HTTP 409).

The statement's usage figure, `actual_aum_used`, is a snapshot taken at creation and never recomputed afterward. The measurement window is the half-open calendar year opening January 1 of `period_year` and closing at January 1 of the following year. Every grazing assignment on the lease's pasture that ended `COMPLETED` or `SHORTENED` contributes: the overlap in days between the assignment's actual grazing window — from its `start_date` up to but not including its `actual_end_date` — and the measurement window is multiplied by that assignment's `daily_demand_aum`, each contribution rounded half-up to 2 decimal places, and the contributions are summed and rounded half-up to 2 decimal places. Assignments still `ACTIVE` and assignments that were `CANCELLED` are excluded from the measurement entirely.

Charges follow the lease's `settlement_basis`. The overage figure is the amount by which `actual_aum_used` exceeds the `aum_allotment`, or zero when usage stayed within the allotment. The `overage_charge_cents` bills the portion of that overage up to `overage_tier1_cap_aum` at `overage_tier1_rate_cents`, and any remaining overage beyond the tier-1 cap at `overage_tier2_rate_cents`, the sum rounded half-up to 2 decimal places. Under the `ALLOTMENT` basis the `base_charge_cents` is the full take-or-pay amount — the `aum_allotment` multiplied by `rate_per_aum_cents` — regardless of how little was actually grazed. Under the `ACTUAL_USE` basis the `base_charge_cents` is the greater of `actual_aum_used` and the `minimum_commit_aum` floor, multiplied by `rate_per_aum_cents` and rounded half-up to 2 decimal places; identical usage below the allotment therefore yields a lower total under `ACTUAL_USE` than under `ALLOTMENT`. The `total_due_cents` is the base charge plus the overage charge.

The statement's `statement_status` walks `DRAFT` to `ISSUED` to `APPROVED` to `PAID`, and `PAID` is terminal. The `RangeManager` who generated the statement — whose identity is frozen into `recorded_by_user_id` at creation — may issue it. Approval belongs to a `RanchManager`, and per §2.10 the approver's `X-User-ID` must differ from `recorded_by_user_id`, with a violation rejected as `ERR_SEGREGATION_OF_DUTIES`; approval stamps `approved_by_user_id`. Finally, a `RanchManager` marks an approved statement paid.

### 3.3. Herd Groups and Supplement Programs

Cattle are managed in groups, never as individuals. A `HerdManager` creates a herd group under its `ranch_id` with a `group_name`, an `animal_class` of `MATURE_COW`, `REPLACEMENT_HEIFER`, or `GROWING`, the current `head_count`, and the group's `avg_weight_lbs` — an average shrunk body weight. A group starts `ACTIVE` with `marked_open_head` at zero and `retained_from_crop_id` null. After creation, a group's `head_count` moves through exactly two mechanisms: herd reductions (§3.8) and replacement-heifer retention (§3.6).

The group's class and weight together determine its animal-unit factor, the conversion from head to forage demand used by both grazing reservations and drought math. The base factor is 1.00 for a `MATURE_COW` group, 0.70 for a `REPLACEMENT_HEIFER` group, and 0.75 for a `GROWING` group. Weight then adjusts the base: take the amount by which the group's `avg_weight_lbs` exceeds the 1,000-pound reference weight — zero when the group averages at or below it — divide that excess by 1,000, multiply by the weight coefficient 0.30, add one, and multiply by the class base. The resulting animal-unit factor is rounded half-up to 4 decimal places. A 1,000-pound mature cow thus factors at exactly 1.0000, while heavier or lighter groups drift upward or downward in proportion.

Supplement programs hang off herd groups. A `HerdManager` creates a program with the `herd_group_id` and `ranch_id`, a `program_type` of `MINERAL`, `PROTEIN`, or `ENERGY`, an inclusive feeding window from `start_date` through `end_date`, a target `feed_rate_oz_per_head_day`, and the delivered `cost_cents_per_ton`. The program's `program_status` is `ACTIVE` from creation. Its `projected_consumption_lbs` is computed once from the group's `head_count` at creation: that head count, multiplied by the number of days in the feeding window counting both the first and last day, multiplied by the feed rate in ounces, and divided by 16 to convert ounces to pounds, rounded half-up to 2 decimal places.

Deliveries accumulate against a program while it remains `ACTIVE`; each delivery records `delivered_lbs` and a `delivery_date`, adds the delivered weight into `delivered_lbs_total`, and recomputes `cost_to_date_cents` as the total delivered pounds divided by 2,000 to yield tons and multiplied by `cost_cents_per_ton`, rounded half-up to 2 decimal places. Completing a program moves it to `COMPLETED` and cancelling moves it to `CANCELLED`; both are terminal, and a program in either state refuses further deliveries or lifecycle actions with `ERR_ALREADY_TERMINAL`.

### 3.4. Breeding Seasons, the Bull Battery, and Turnouts

A breeding season plans one cow group's exposure. A `HerdManager` creates the season with its `ranch_id`, the `herd_group_id` of the cow group being bred, the `season_year`, and a planned window from `planned_turnout_date` through `planned_removal_date`. The `exposed_head_count` — the number of females exposed — may not exceed the group's current `head_count`, or creation fails with `ERR_EXPOSURE_EXCEEDS_GROUP` (HTTP 422). The system derives the season's `required_bull_count` at one bull for every 25 exposed females, rounded up to a whole bull. The season's `season_status` opens at `PLANNED`.

Bulls are registered individually with their `ranch_id`, ear `tag`, `breed`, and `birth_year`. A new bull's `bse_status` is `UNTESTED` and its `life_status` is `ACTIVE`, with `last_bse_date`, `last_bse_result`, and `scrotal_cm` all null until the first exam is recorded. Breeding soundness is established by recording an exam: a `HerdManager` supplies the `result` — `PASSED` or `FAILED` — the `exam_date`, and the `scrotal_cm` measurement, and the system records `last_bse_date`, `last_bse_result`, and `scrotal_cm` on the bull. Exams may be recorded only while the bull's `life_status` is `ACTIVE`. A `FAILED` result moves the bull to `FAILED` from any prior state, and a later `PASSED` result — a retest — returns the bull to `PASSED` from `FAILED`, from `EXPIRED`, or even from a previous `PASSED`; the retest loop is cyclic and unrestricted.

A passing exam does not stay valid forever. When the current date moves strictly past `last_bse_date` plus the system's breeding-soundness validity window, a bull's `bse_status` lapses from `PASSED` to `EXPIRED`. Like the other lazy derivations of §2.4, this expiry is recomputed whenever the bull is read and whenever a season's battery is evaluated — no background job is involved.

Retirement removes a bull from the battery. A `HerdManager` retires a bull with a `disposition` of `SOLD`, `CULLED`, or `DEAD`, and the bull's `life_status` takes that value; all three are terminal. Retirement is refused while the bull has any turnout still in `SCHEDULED` or `TURNED_IN` — a bull committed to a breeding pasture must be removed from it first.

Turnouts join bulls to seasons. Scheduling a turnout takes the `bull_id`, the `breeding_season_id`, and a `ranch_id` that must match both the bull's ranch and the season's ranch, plus a `turnout_date` and `planned_removal_date` that form a closed interval — both endpoints count as days with the cows. That interval must lie within the season's planned window, or scheduling fails with `ERR_TURNOUT_OUTSIDE_SEASON_WINDOW` (HTTP 422). Two temporal conflict rules then guard the individual bull, evaluated in this pinned order. First, the new closed interval may not intersect any existing `SCHEDULED` or `TURNED_IN` turnout of the same bull — an inclusive-intersection test — or the request fails with `ERR_BULL_TURNOUT_OVERLAP` (HTTP 409). Second, the bull must get its turnaround rest: fewer than 7 days between the new turnout and any non-cancelled turnout of that bull, where the existing turnout's end is taken as its `actual_removal_date` when it was `REMOVED` and its `planned_removal_date` otherwise, fails with `ERR_BULL_TURNAROUND_TOO_SHORT` (HTTP 409). A turnout that survives both checks is born with `turnout_status` of `SCHEDULED`.

From `SCHEDULED`, the turnout is either turned in or cancelled. Turning in — moving `SCHEDULED` to `TURNED_IN` — is permitted while the season is `PLANNED` or `BREEDING`. Removing a turned-in bull moves the turnout to `REMOVED` and stamps its `actual_removal_date` from the supplied `removal_date`. Cancelling a `SCHEDULED` turnout moves it to `CANCELLED`; `REMOVED` and `CANCELLED` are both terminal.

Breeding begins only when the battery is sufficient. Advancing the season from `PLANNED` to `BREEDING` counts this season's turnouts that are `TURNED_IN` whose bulls are still `ACTIVE` in life and whose `bse_status` is `PASSED` — with lazy expiry applied against the current date at evaluation time — and if that count falls short of the season's `required_bull_count`, the advance is rejected with `ERR_BULL_BATTERY_INSUFFICIENT` (HTTP 422). Ending the breeding window moves the season from `BREEDING` to `GESTATION`, and is permitted only once no turnout of the season remains `TURNED_IN` — every bull must be `REMOVED` or `CANCELLED` first.

### 3.5. Pregnancy Checking and Season Closeout

Once a season has moved to `GESTATION`, a `HerdManager` opens its pregnancy check by supplying the `breeding_season_id`, the `ranch_id`, and the `check_date` of the palpation or ultrasound work. A season still in any other state refuses the check with `ERR_SEASON_NOT_IN_GESTATION` (HTTP 400), and because exactly one pregnancy check may exist per season, a second attempt against the same season fails with `ERR_PREG_CHECK_ALREADY_EXISTS` (HTTP 409). Creating the check snapshots the season's `exposed_head_count` onto the check itself and pushes the season from `GESTATION` into `PREG_CHECK`; the check's `check_status` is born `DRAFT`.

Finalization is where the herd learns its conception rate. The `HerdManager` supplies `pregnant_count`, `open_count`, and `dead_count`, and the three must sum exactly to the check's snapshotted `exposed_head_count` — any other arithmetic is rejected with `ERR_PREG_COUNT_MISMATCH` (HTTP 422). A finalized check computes its `pregnancy_rate_pct` — null while the check sits in `DRAFT` — as 100 multiplied by `pregnant_count` and divided by `exposed_head_count`, rounded half-up to 1 decimal place. Two cascades follow at the same moment: the `open_count` is added onto the bred herd group's `marked_open_head`, flagging those head as cull candidates, and the season itself moves from `PREG_CHECK` to `CLOSED`, its terminal state. The finalized check, in `FINALIZED`, is likewise terminal.

### 3.6. The Calf Crop: Weaning, Preconditioning, and Heifer Retention

Branding day creates the calf crop. A `HerdManager` registers the crop against a `breeding_season_id` and `ranch_id` with the `crop_year` and the live counts `steer_head` and `heifer_head`. The season must already have moved past the breeding window — `GESTATION`, `PREG_CHECK`, or `CLOSED` all accept a crop, while anything earlier rejects it with `ERR_SEASON_NOT_IN_GESTATION`. A calf crop tracks three independent status axes at once: `wean_status` begins `UNWEANED`, `precon_status` begins `NONE`, and `lifecycle_status` begins `ACTIVE`, with every head counter — `retained_heifer_head`, `death_loss_steer_head`, `death_loss_heifer_head`, `marketed_steer_head`, `marketed_heifer_head`, `reserved_steer_head`, and `reserved_heifer_head` — starting at zero.

Weaning is recorded by a `HerdManager` with the `weaning_date` — which may not lie in the future relative to the current date — together with `avg_wean_weight_lbs`, `avg_wean_age_days`, `avg_birth_weight_lbs`, and `avg_dam_age_years`. Recording weaning moves the crop from `UNWEANED` to `WEANED` and computes both variants of the adjusted 205-day weight, which sit null until that moment. The age-only variant, `adj205_age_only_lbs`, takes the difference between average weaning weight and average birth weight, divides it by the average weaning age in days, multiplies by 205, adds the average birth weight back, and rounds half-up to 1 decimal place; it is the figure used for within-crop comparisons. The dam-adjusted variant, `adj205_dam_adjusted_lbs`, adds a dam-age adjustment to the age-only figure and is likewise rounded half-up to 1 decimal place: 54 pounds when the average dam age is two years, 20 pounds when it is three years, no adjustment for dams aged four through ten years, and 20 pounds again for dams eleven years or older. For a crop whose dams average two years old, the two variants therefore diverge by exactly +54.0 pounds. The dam-adjusted figure is the one that backs preconditioning marketing claims.

Preconditioning runs on its own axis, independent of weaning. Enrolling the crop moves `precon_status` from `NONE` to `ENROLLED` and is permitted even while the calves are still `UNWEANED` — enrollment is a program signup, not a biological event. Vaccination rounds are recorded one at a time with a `round_number` and a `vaccine_date`; the first round stamps `vaccine_round_1_date` and the second stamps `vaccine_round_2_date`. The second round requires the first to already be on record and must fall at least 14 days after it — recording round two before round one, or inside that 14-day spacing, is rejected with `ERR_VACCINE_SPACING_VIOLATION` (HTTP 422).

Certification is the payoff, and it is gated by four prerequisites evaluated under the validation cascade of §2.8. The crop must be `ENROLLED`, or the attempt fails with `ERR_PRECON_NOT_ENROLLED` (HTTP 400). It must be `WEANED`, failing with `ERR_CROP_NOT_WEANED` (HTTP 400) otherwise. Both vaccine rounds must be on record, failing with `ERR_PRECON_VACCINE_INCOMPLETE` (HTTP 422) when either is missing. And the current date must be at least 45 days past the `weaning_date` — exactly 45 days qualifies — failing with `ERR_PRECON_DAYS_INSUFFICIENT` (HTTP 422) when fewer have elapsed. A crop that clears all four moves from `ENROLLED` to `CERTIFIED`.

Replacement-heifer retention moves heifers out of the marketable pool and into the breeding herd. Retaining takes a `head_count` and a `target_herd_group_id`; the target must be a `REPLACEMENT_HEIFER`-class group on the same ranch that has not been `LIQUIDATED`, with violations rejected as `ERR_RETENTION_CLASS_MISMATCH` (HTTP 422), and the count may not exceed the crop's `available_heifer_head`, or the retain fails with `ERR_RETENTION_EXCEEDS_AVAILABLE` (HTTP 422). Retaining adds the head to the crop's `retained_heifer_head` — which lowers `available_heifer_head` by the same amount — and adds them to the target group's `head_count`; the first retention into a group also pins that group's `retained_from_crop_id` to the crop's `id`, and that pin is what later gates reversal. Unretaining flows the other way: naming a `source_herd_group_id` whose `retained_from_crop_id` must point back at this crop, with a `head_count` no greater than the crop's `retained_heifer_head` (again `ERR_RETENTION_EXCEEDS_AVAILABLE`); the source group's `head_count` and the crop's `retained_heifer_head` both fall by the count, returning those heifers to the marketable pool.

Death loss is recorded by class: a `calf_class` of `STEER` or `HEIFER`, a `head_count`, and a `loss_date`. The loss increments `death_loss_steer_head` or `death_loss_heifer_head` accordingly, and a loss larger than the available head of that class is refused with `ERR_INSUFFICIENT_CROP_HEAD` (HTTP 422).

Availability bookkeeping ties the whole crop together. The `available_steer_head` is the `steer_head` minus `death_loss_steer_head`, minus `reserved_steer_head`, minus `marketed_steer_head`; the `available_heifer_head` subtracts `death_loss_heifer_head`, `reserved_heifer_head`, `marketed_heifer_head`, and additionally `retained_heifer_head` from the `heifer_head`. The reserved counters track head sitting on sale lots in `OFFERED`, `CONTRACTED`, `DELIVERED`, or `DISPUTED`, while the marketed counters track head on lots that have reached `SETTLED`. After any event that moves these counters — a settle, a retain, an unretain, a death loss, or a lot cancellation — the crop re-evaluates its closure predicate: when both available counts have reached zero and no sale lot of the crop remains in `DRAFT`, `OFFERED`, `CONTRACTED`, `DELIVERED`, or `DISPUTED`, the crop's `lifecycle_status` bubbles up to `CLOSED` on its own. Closure is terminal, and any attempt to create a new sale lot against a closed crop is rejected with `ERR_ALREADY_TERMINAL` (HTTP 400).

### 3.7. Calf Marketing: Sale Lots and Settlement

Marketing begins when a `SalesAgent` drafts a sale lot against a calf crop. The lot names its `calf_crop_id` and a `ranch_id` that must equal the crop's ranch, a `lot_class` of `STEER` or `HEIFER`, the `head_count` on the lot, and its full commercial terms: `base_price_cents_per_cwt` at the reference `base_weight_lbs`, the `slide_cents_per_lb` that adjusts price for pay-weight deviation, the `shrink_pct` applied to delivered weight, a `precon_claim` of `NONE`, `ENROLLED`, or `CERTIFIED`, the `freight_cents_per_head` deduction, and the `commission_pct` of gross. Creation enforces the marketing gates: the crop must be `WEANED` (`ERR_CROP_NOT_WEANED`), its lifecycle must still be `ACTIVE` — a closed crop yields `ERR_ALREADY_TERMINAL` — the crop's available head of the lot's class must cover the lot's `head_count` (`ERR_INSUFFICIENT_CROP_HEAD`, HTTP 422), and the lot's `precon_claim` may not rank above the crop's own `precon_status`, where `CERTIFIED` outranks `ENROLLED` and `ENROLLED` outranks `NONE` (`ERR_PRECON_CLAIM_EXCEEDS_CROP`, HTTP 422). A lot that clears the gates is born with `lot_status` of `DRAFT` and with `sold_by_user_id` stamped from the creating `SalesAgent`.

Offering publishes the lot. Moving from `DRAFT` to `OFFERED` re-verifies that the crop's lifecycle is still `ACTIVE` and that the crop's available head of the lot's class still covers the lot's `head_count` — availability can have moved since drafting — and then reserves the head: the crop's `reserved_steer_head` or `reserved_heifer_head`, matching the lot's class, increases by the lot's `head_count`. Contracting an offered lot records the `buyer_name` and moves it to `CONTRACTED`. When a buyer defaults, relisting returns the lot from `CONTRACTED` to `OFFERED`, increments its `relist_count`, and clears the `buyer_name`; the offer–contract cycle is unrestricted in count.

Delivery is where the money is computed. Delivering a contracted lot takes the scale-house `delivered_avg_weight_lbs` and moves the lot to `DELIVERED`, and at that moment the full settlement — every one of the seven figures from `pay_weight_lbs` through `net_settlement_cents`, all null until now — is computed in a pinned order. First, `pay_weight_lbs` is the delivered average weight reduced by the shrink fraction — the delivered weight multiplied by one minus `shrink_pct`, rounded half-up to 2 decimal places. Second, the slide: the `base_price_cents_per_cwt` is adjusted by the difference between `base_weight_lbs` and the pay weight, multiplied by `slide_cents_per_lb`, and the adjustment is signed in both directions — a pay weight lighter than base raises the price, a heavier one lowers it. Third, the slid price is floored: if it has fallen below 100 cents per hundredweight it is raised to exactly 100, and only then is the preconditioning premium added — nothing for a `NONE` claim, 250 cents per hundredweight for `ENROLLED`, and 600 for `CERTIFIED` — yielding `final_price_cents_per_cwt`, rounded half-up to 2 decimal places. Fourth, `per_head_gross_cents` is the final price multiplied by the pay weight and divided by 100, rounded half-up to 2 decimal places; `gross_cents` is then that rounded per-head figure multiplied by the `head_count` — the system rounds per head first and multiplies second, never the other way around. Fifth, `commission_cents` is the gross multiplied by `commission_pct`, rounded half-up to 2 decimal places, while `freight_cents` is the whole-number product of `head_count` and `freight_cents_per_head`. Finally, `net_settlement_cents` is the gross minus the commission minus the freight.

Disputes pause a delivered lot without unwinding it. Disputing moves `DELIVERED` to `DISPUTED` with a recorded `reason`. Resolving the dispute returns the lot to `DELIVERED`, and when the resolution supplies an `adjusted_delivered_weight_lbs`, that figure replaces `delivered_avg_weight_lbs` and the entire settlement chain above is recomputed from it.

Settlement is the terminal act and belongs to the `RanchManager` — but never to one who also sold the lot: per §2.10 the settler's `X-User-ID` must differ from `sold_by_user_id`, with a violation rejected as `ERR_SEGREGATION_OF_DUTIES`. Settling stamps `settled_by_user_id`, moves the lot to `SETTLED`, and then cascades twice into the crop: first the crop's reserved counter for the lot's class decreases by the `head_count` while its marketed counter increases by the same amount, and second that marketed-head mutation re-evaluates the crop's closure predicate from §3.6, closing the crop when every head is accounted for. A lot still in `DRAFT` or `OFFERED` may instead be cancelled, moving to `CANCELLED`; cancelling an offered lot releases its reservation — the crop's reserved counter for the class falls by the `head_count` — and re-evaluates the closure predicate. `SETTLED` and `CANCELLED` are both terminal.

### 3.8. Drought Assessment and the Destocking Protocol

Drought management begins with measurement. A `RangeManager` creates a drought assessment with the `ranch_id`, the `assessment_date` of the field work, and `pasture_measurements` — one entry per pasture pairing each `pasture_id` with its observed `production_pct_of_normal`. The measurements must cover every pasture of the ranch that is not closed exactly once: a missing pasture, a duplicated pasture, or a reference to an unknown pasture all fail creation with `ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE` (HTTP 422). The assessment's `assessment_status` is born `DRAFT`, and creation computes a preview without mutating the ranch.

Four figures make up that preview. The `ranch_production_pct` is the capacity-weighted production percentage: each measured pasture contributes its `base_capacity_aum` multiplied by its `production_pct_of_normal`, the contributions are summed and divided by the total `base_capacity_aum` of the measured pastures, and the quotient is rounded half-up to 1 decimal place. The `resulting_posture` maps that percentage onto the four postures: 90 or higher yields `NORMAL`, at least 75 but below 90 yields `WATCH`, at least 55 but below 75 yields `ALERT`, and below 55 yields `CRITICAL`. The `monthly_supply_aum` spreads the posture-scaled capacity across the season: each non-closed pasture contributes its `base_capacity_aum` multiplied by the posture factor of the resulting posture — 1.00 for `NORMAL`, 0.85 for `WATCH`, 0.70 for `ALERT`, 0.50 for `CRITICAL` — the contributions are summed and divided by the five months of the grazing season, rounded half-up to 2 decimal places. The `monthly_demand_aum` sums, over every herd group of the ranch whose `group_status` is not `LIQUIDATED`, the group's `head_count` multiplied by its animal-unit factor per §3.3, rounded half-up to 2 decimal places. The `deficit_aum_per_30d` is the demand minus the supply, rounded half-up to 2 decimal places.

Finalization is the second OCC-guarded operation in the system. The `RangeManager`'s request must carry `expected_ranch_version` equal to the ranch's current `version`; if any write has advanced the ranch's version since the client last read it, the finalize is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be re-based on the fresh state. A successful finalize — permitted only from `DRAFT` — writes the assessment's `resulting_posture` onto the ranch's `drought_posture`, copies the assessment's `ranch_production_pct` onto the ranch, increments the ranch's `assessment_seq` by one, and increments the ranch's `version` by one. Posture moves freely between any of its four values from one finalized assessment to the next; the posture axis has no terminal state.

When the finalized `deficit_aum_per_30d` is strictly greater than zero — whatever posture resulted — finalization also creates a destock order whose `order_status` opens at `OPEN`, and that single creation is the cause of a ranch-wide cascade: every herd group on the ranch whose `group_status` is `ACTIVE` flips to `DESTOCKING`. The order's `ranch_id` and `drought_assessment_id` point back at their origins, and its `deadline_date` is the assessment's `assessment_date` plus the ranch's `destock_grace_days`.

The order's `required_reduction_head` is computed by a single left-to-right pass with no re-iteration, so the result is fully determined. Candidate herd groups are sorted by class priority — `GROWING` groups first, then `MATURE_COW`, then `REPLACEMENT_HEIFER` — within a class by descending `avg_weight_lbs` so heavier groups are drawn first, and remaining ties by each group's `created_at` in ascending order. Each group's per-head monthly forage demand is simply its animal-unit factor. The pass walks the sorted groups once, and while any deficit remains it draws from each group in turn: the head taken from a group is the smaller of that group's current `head_count` and the outstanding deficit divided by the group's per-head demand, rounded up to a whole head; the taken head accumulates into `required_reduction_head`, and the outstanding deficit falls by the taken head multiplied by that per-head demand before the pass moves to the next group.

Compliance is built up through herd reductions. A `HerdManager` records a reduction on a group with a `head_count`, a `reason` — sale, cull, death, transfer, or `LIQUIDATION` — and optionally a `destock_order_id`. The reduction may not exceed the group's current `head_count`, and a `LIQUIDATION` must take the group's full remaining head exactly; either violation is rejected with `ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD` (HTTP 422). Every reduction subtracts its head from the group's `head_count`, and when a `destock_order_id` is supplied and that order is `OPEN` or `EXPIRED`, the order's `received_reduction_head` grows by the reduced head — a reduction that references an already-resolved order simply receives no credit toward it. A liquidation additionally moves the group to `LIQUIDATED`, zeroes its head, and removes it from all future destock demand calculations.

An order is resolved in one of three ways. Verifying compliance — a `RangeManager` action — compares the accumulated `received_reduction_head` against the `required_reduction_head`: when the received head has reached the requirement, the order becomes `COMPLIANT`, and this holds whether the order was `OPEN` or had already slipped to `EXPIRED`; when the ranch is short and the current date has passed the `deadline_date`, an `OPEN` order instead becomes `EXPIRED` — an outcome that leaves the commitment gate unchanged, since `OPEN` and `EXPIRED` orders both keep blocking new grazing commitments under §2.11. Alternatively, a `RanchManager` may waive an `OPEN` or `EXPIRED` order, supplying a non-empty `waiver_note`, moving it to `WAIVED`. Whenever an order reaches `COMPLIANT` or `WAIVED`, herd groups return from `DESTOCKING` to `ACTIVE` — a group leaves `DESTOCKING` once every order covering it has resolved, and the cycle between `ACTIVE` and `DESTOCKING` may repeat across successive assessments. `COMPLIANT`, `WAIVED`, and `EXPIRED` are the order's end states, with one deliberate exception: an `EXPIRED` order may still be moved to `COMPLIANT` by a later verification or to `WAIVED` by a waiver, while `COMPLIANT` and `WAIVED` accept no further transitions.

### 3.9. Grazing Assignments and Forage Accounting

The grazing assignment is where the forage ledger meets the ground: it commits a herd group to a pasture for a planned window. A `RangeManager` creates one with the `pasture_id`, the `herd_group_id`, and a `ranch_id` that must match both sides, plus a `start_date` and `planned_end_date` that define a half-open window — the start day counts as grazed, the planned end day does not. The window's length in days is the assignment's `grazing_days`. Creation snapshots the herd group's `head_count` and its animal-unit factor into the assignment's `au_factor` — 4 decimal places — and derives the `daily_demand_aum` as the snapshotted head count multiplied by the snapshotted factor and divided by the 30-day AUM month, kept unrounded. The `reserved_aum` is then the daily demand multiplied by `grazing_days`, rounded half-up to 2 decimal places, while `consumed_aum` and `actual_end_date` sit null until the assignment ends. Because both inputs are snapshots, later changes to the group's head count never retroactively move an existing reservation. The assignment is `ACTIVE` from the moment of creation, and its `reserved_aum` is immediately added into the pasture's `committed_aum`.

Creation is the most heavily gated operation in the system, and the checks fire in the cascade order of §2.8 — the pasture-condition gate, the lease-coverage gate, the two drought gates in their pinned sub-order, the two pasture temporal rules in theirs, lease-window nesting, and finally the forage budget, with the first failure determining the error. The pasture must not be `CLOSED`, or the create fails with `ERR_PASTURE_NOT_GRAZEABLE`; recall from §2.9 that a `RESTING` pasture does not fail this gate, because rest is enforced by the buffer rule below rather than by the status itself. When the pasture's tenure is `LEASED`, at least one `ACTIVE` lease must cover it — deeded ground carries no lease requirement — and the absence of any active covering lease fails with `ERR_LEASE_NOT_ACTIVE`. Then the drought gates of §2.11: an `OPEN` or `EXPIRED` destock order on the ranch blocks with `ERR_DESTOCK_ORDER_BLOCKING` before the posture check can surface `ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT` under `ALERT` or `CRITICAL`.

Temporal placement comes next. The new half-open window may not intersect the half-open window of any existing `ACTIVE` assignment on the same pasture — intersection under half-open semantics means the new start falls strictly before the existing end and the new end falls strictly after the existing start — and a collision is `ERR_PASTURE_WINDOW_OVERLAP` (HTTP 409). Only after overlap is clear does the rest-buffer rule run: the gap between the new window and every other non-cancelled assignment on the pasture, in either direction, must be at least the pasture's `min_rest_days`, where an existing assignment's end is taken as its `actual_end_date` when it ended `COMPLETED` or `SHORTENED` and its `planned_end_date` while still `ACTIVE`; a tighter gap fails with `ERR_PASTURE_REST_VIOLATION` (HTTP 409). Window nesting follows for leased ground: when an `ACTIVE` covering lease exists but the assignment's window from `start_date` to `planned_end_date` does not lie within the lease's inclusive window from its `start_date` to its `end_date`, the create is rejected with `ERR_ASSIGNMENT_OUTSIDE_LEASE_WINDOW` (HTTP 422). Last, the budget check of §2.9: the computed `reserved_aum` must not exceed the pasture's `available_aum` — an exact fit is permitted, and only a strict excess draws `ERR_AUM_BUDGET_EXCEEDED` (HTTP 422).

Ending grazing is a single action with two outcomes. A `RangeManager` completes an active assignment with an `actual_end_date`, which may not fall before the assignment's `start_date` and may not lie in the future relative to the current date. When the actual end equals the `planned_end_date` the assignment closes as `COMPLETED`; an earlier actual end — the early-out case, drought-driven or otherwise — closes it as `SHORTENED`. Either way the `consumed_aum` is the assignment's `daily_demand_aum` multiplied by the actual days grazed from `start_date` up to but not including `actual_end_date`, rounded half-up to 2 decimal places; the full `reserved_aum` comes off the pasture's `committed_aum`, which on a shortened stay returns the ungrazed remainder to `available_aum`; and the pasture's `resting_until` is set to the `actual_end_date` plus the pasture's `min_rest_days`, putting the ground into `RESTING` until the current date catches up. An assignment that has not yet begun may instead be cancelled — permitted only while the current date is still earlier than its `start_date` — which moves it to `CANCELLED`, releases its full reservation from the pasture's `committed_aum`, and records a `consumed_aum` of zero. `COMPLETED`, `SHORTENED`, and `CANCELLED` are all terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. The table below is a routing summary only — request fields, computed results, side effects, and the business conditions guarding each operation are defined by the narratives of §2 and §3, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | RanchManager |
| POST | `/api/ranches` | Create a ranch | RanchManager |
| GET | `/api/ranches/{id}` | Get a ranch | RanchManager, RangeManager, HerdManager, SalesAgent |
| PATCH | `/api/ranches/{id}` | Update ranch policy fields | RanchManager |
| POST | `/api/pastures` | Create a pasture | RangeManager |
| GET | `/api/pastures/{id}` | Get a pasture, with condition and AUM figures recomputed | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/pastures` | List pastures with filters | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/pastures/{id}/close` | Close a pasture (terminal) | RangeManager |
| POST | `/api/grazing-leases` | Create a grazing lease in `DRAFT` | RangeManager |
| GET | `/api/grazing-leases/{id}` | Get a lease, with lazy expiry applied | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/grazing-leases` | List leases | RanchManager, RangeManager, HerdManager, SalesAgent |
| PATCH | `/api/grazing-leases/{id}` | Amend lease terms (OCC-guarded) | RangeManager |
| POST | `/api/grazing-leases/{id}/activate` | Activate a lease | RangeManager |
| POST | `/api/grazing-leases/{id}/suspend` | Suspend a lease | RangeManager |
| POST | `/api/grazing-leases/{id}/reinstate` | Reinstate a suspended lease | RangeManager |
| POST | `/api/grazing-leases/{id}/terminate` | Terminate a lease | RanchManager |
| POST | `/api/lease-statements` | Generate a settlement statement for a lease and year | RangeManager |
| GET | `/api/lease-statements/{id}` | Get a statement | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/lease-statements` | List statements | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/lease-statements/{id}/issue` | Issue a statement | RangeManager |
| POST | `/api/lease-statements/{id}/approve` | Approve a statement (segregated from recorder) | RanchManager |
| POST | `/api/lease-statements/{id}/mark-paid` | Mark an approved statement paid | RanchManager |
| POST | `/api/herd-groups` | Create a herd group | HerdManager |
| GET | `/api/herd-groups/{id}` | Get a herd group | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/herd-groups` | List herd groups | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/herd-groups/{id}/reductions` | Record a head reduction, optionally crediting a destock order | HerdManager |
| POST | `/api/breeding-seasons` | Create a breeding season | HerdManager |
| GET | `/api/breeding-seasons/{id}` | Get a breeding season | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/breeding-seasons` | List breeding seasons | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/breeding-seasons/{id}/begin-breeding` | Begin breeding (bull battery gate) | HerdManager |
| POST | `/api/breeding-seasons/{id}/end-breeding` | End the breeding window | HerdManager |
| POST | `/api/bulls` | Register a bull | HerdManager |
| GET | `/api/bulls/{id}` | Get a bull, with lazy BSE expiry applied | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/bulls` | List bulls | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/bulls/{id}/record-bse` | Record a breeding soundness exam | HerdManager |
| POST | `/api/bulls/{id}/retire` | Retire a bull from the battery | HerdManager |
| POST | `/api/bull-turnouts` | Schedule a bull turnout | HerdManager |
| GET | `/api/bull-turnouts/{id}` | Get a turnout | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/bull-turnouts` | List turnouts | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/bull-turnouts/{id}/turn-in` | Mark a bull turned in | HerdManager |
| POST | `/api/bull-turnouts/{id}/remove` | Remove a bull from the breeding pasture | HerdManager |
| POST | `/api/bull-turnouts/{id}/cancel` | Cancel a scheduled turnout | HerdManager |
| POST | `/api/preg-checks` | Create a season's pregnancy check | HerdManager |
| GET | `/api/preg-checks/{id}` | Get a pregnancy check | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/preg-checks` | List pregnancy checks | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/preg-checks/{id}/finalize` | Finalize pregnancy counts | HerdManager |
| POST | `/api/calf-crops` | Create a calf crop at branding | HerdManager |
| GET | `/api/calf-crops/{id}` | Get a calf crop | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/calf-crops` | List calf crops | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/calf-crops/{id}/record-weaning` | Record weaning measurements and both adjusted-205 variants | HerdManager |
| POST | `/api/calf-crops/{id}/enroll-preconditioning` | Enroll the crop in preconditioning | HerdManager |
| POST | `/api/calf-crops/{id}/record-vaccine` | Record a vaccine round | HerdManager |
| POST | `/api/calf-crops/{id}/certify-preconditioning` | Certify preconditioning | HerdManager |
| POST | `/api/calf-crops/{id}/retain-heifers` | Retain heifers into a replacement group | HerdManager |
| POST | `/api/calf-crops/{id}/unretain-heifers` | Return retained heifers to the marketable pool | HerdManager |
| POST | `/api/calf-crops/{id}/record-death-loss` | Record calf death loss by class | HerdManager |
| POST | `/api/sale-lots` | Create a draft sale lot | SalesAgent |
| GET | `/api/sale-lots/{id}` | Get a sale lot | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/sale-lots` | List sale lots | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/sale-lots/{id}/offer` | Offer a lot, reserving head from the crop | SalesAgent |
| POST | `/api/sale-lots/{id}/contract` | Contract a lot to a buyer | SalesAgent |
| POST | `/api/sale-lots/{id}/relist` | Return a contracted lot to offered | SalesAgent |
| POST | `/api/sale-lots/{id}/deliver` | Deliver a lot and compute its settlement | SalesAgent |
| POST | `/api/sale-lots/{id}/dispute` | Dispute a delivered lot | SalesAgent |
| POST | `/api/sale-lots/{id}/resolve-dispute` | Resolve a dispute, optionally adjusting weight | SalesAgent |
| POST | `/api/sale-lots/{id}/settle` | Settle a delivered lot (segregated from seller) | RanchManager |
| POST | `/api/sale-lots/{id}/cancel` | Cancel a draft or offered lot | SalesAgent |
| POST | `/api/grazing-assignments` | Create a grazing assignment | RangeManager |
| GET | `/api/grazing-assignments/{id}` | Get an assignment | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/grazing-assignments` | List assignments | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/grazing-assignments/{id}/complete` | End grazing, completed or shortened | RangeManager |
| POST | `/api/grazing-assignments/{id}/cancel` | Cancel an assignment that has not begun | RangeManager |
| POST | `/api/supplement-programs` | Create a supplement program | HerdManager |
| GET | `/api/supplement-programs/{id}` | Get a supplement program | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/supplement-programs` | List supplement programs | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/supplement-programs/{id}/deliveries` | Record a supplement delivery | HerdManager |
| POST | `/api/supplement-programs/{id}/complete` | Complete a program | HerdManager |
| POST | `/api/supplement-programs/{id}/cancel` | Cancel a program | HerdManager |
| POST | `/api/drought-assessments` | Create a drought assessment with preview figures | RangeManager |
| GET | `/api/drought-assessments/{id}` | Get a drought assessment | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/drought-assessments` | List drought assessments | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/drought-assessments/{id}/finalize` | Finalize an assessment (OCC-guarded) | RangeManager |
| GET | `/api/destock-orders/{id}` | Get a destock order | RanchManager, RangeManager, HerdManager, SalesAgent |
| GET | `/api/destock-orders` | List destock orders | RanchManager, RangeManager, HerdManager, SalesAgent |
| POST | `/api/destock-orders/{id}/verify-compliance` | Verify reductions against an order | RangeManager |
| POST | `/api/destock-orders/{id}/waive` | Waive an order | RanchManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined by the narratives of §2 and §3, not repeated here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 400 |
| `ERR_ALREADY_TERMINAL` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PASTURE_NOT_GRAZEABLE` | 400 |
| `ERR_LEASE_NOT_ACTIVE` | 400 |
| `ERR_SEASON_NOT_IN_GESTATION` | 400 |
| `ERR_CROP_NOT_WEANED` | 400 |
| `ERR_PRECON_NOT_ENROLLED` | 400 |
| `ERR_PASTURE_WINDOW_OVERLAP` | 409 |
| `ERR_PASTURE_REST_VIOLATION` | 409 |
| `ERR_BULL_TURNOUT_OVERLAP` | 409 |
| `ERR_BULL_TURNAROUND_TOO_SHORT` | 409 |
| `ERR_PREG_CHECK_ALREADY_EXISTS` | 409 |
| `ERR_DUPLICATE_STATEMENT_PERIOD` | 409 |
| `ERR_AUM_BUDGET_EXCEEDED` | 422 |
| `ERR_LEASE_CAPACITY_EXCEEDED` | 422 |
| `ERR_ALLOTMENT_BELOW_RECORDED_USAGE` | 422 |
| `ERR_ASSIGNMENT_OUTSIDE_LEASE_WINDOW` | 422 |
| `ERR_TURNOUT_OUTSIDE_SEASON_WINDOW` | 422 |
| `ERR_DROUGHT_POSTURE_BLOCKS_COMMITMENT` | 422 |
| `ERR_DESTOCK_ORDER_BLOCKING` | 422 |
| `ERR_BULL_BATTERY_INSUFFICIENT` | 422 |
| `ERR_EXPOSURE_EXCEEDS_GROUP` | 422 |
| `ERR_PREG_COUNT_MISMATCH` | 422 |
| `ERR_RETENTION_EXCEEDS_AVAILABLE` | 422 |
| `ERR_RETENTION_CLASS_MISMATCH` | 422 |
| `ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD` | 422 |
| `ERR_VACCINE_SPACING_VIOLATION` | 422 |
| `ERR_PRECON_VACCINE_INCOMPLETE` | 422 |
| `ERR_PRECON_DAYS_INSUFFICIENT` | 422 |
| `ERR_PRECON_CLAIM_EXCEEDS_CROP` | 422 |
| `ERR_INSUFFICIENT_CROP_HEAD` | 422 |
| `ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE` | 422 |
