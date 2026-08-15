# Irrigation Water Allocation API — Product Requirements Document

## 1. Introduction

Western irrigation districts operate under a doctrine of prior appropriation: the right to divert water belongs to those who claimed it first, and in a dry year the most senior rights are satisfied before junior claims receive a single acre-foot. The district office that administers such a system must simultaneously manage per-season allocation ledgers for every irrigator, schedule physical water deliveries through a canal network with finite capacity, dispatch field riders to measure actual flows at each turnout, bill users for the season's assessments, and — when the board declares drought — curtail junior users while protecting senior entitlements. Each of these concerns interacts with the others: a lien filed for nonpayment blocks new orders, a maintenance shutdown cancels scheduled deliveries, and an effectuated drought declaration can cascade-cancel orders whose committed water no longer fits within a reduced entitlement.

This document specifies the API through which a district operates that entire lifecycle. Three kinds of actors interact with the system: district office staff who administer seasons, accounts, billing, canal infrastructure, and drought declarations; irrigators who place water orders against their own accounts, transfer allocation between accounts, and pay their assessments; and field riders who physically open turnouts and record measured flows. Because allocation decisions have legal and financial consequences, every quantity the system reports — entitlements, committed balances, delivered volumes, invoice line items — is derived through pinned calculation rules stated here, and every state transition that moves water through the district is guarded by explicit preconditions paired with named error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting party and `X-User-Role` naming the caller's role. The three declared roles are `DistrictAdmin`, `DitchRider`, and `WaterUser`. A request missing either header, or presenting a role string outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint, or whose ownership check fails, is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles bind `X-User-ID` to identity differently. When `X-User-Role` is `WaterUser`, `X-User-ID` is the `id` of the acting `WaterAccount`; ownership checks on any resource that references a `WaterAccount` compare the resource's foreign-key field to `X-User-ID` — an irrigator places orders, cancels their own orders, requests transfers from their own account, cancels their own transfers, and pays their own invoices, and each of these calls is authorized by matching the caller's `X-User-ID` to the referenced account id. When `X-User-Role` is `DistrictAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; district staff exercise every administrative operation but are never compared against any entity's `id`. When `X-User-Role` is `DitchRider`, `X-User-ID` is likewise an opaque operator identifier — it is not the `id` of any persisted entity, but it is recorded as the `rider_user_id` field on each `RiderWorkOrder` at scheduling time, and the assignment-sensitive rider operations (starting a scheduled order, submitting a measurement) are authorized by comparing the caller's `X-User-ID` to the stored `rider_user_id` of the linked work order.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are returned in `created_at` ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the request identifiers.

### 2.4. Common Resource Properties, Monetary Precision, and the District's Ledger Principle

Every persisted resource carries an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and a `version` integer. Both timestamps are ISO 8601 UTC values with three fractional digits. `version` starts at the value assigned at creation and increments by exactly 1 on every mutation of the owning entity; clients observe it on reads and present it back to the server through the optimistic-concurrency fields described in §2.6. All entities in this system — water accounts, seasons, allocations, turnout orders, rider work orders, assessment invoices, canal reaches, maintenance windows, transfer requests, and drought declarations — carry the full common set.

All water volumes are expressed in acre-feet and all monetary amounts in dollars. Every computed quantity the district relies on — order volumes, measured deliveries, entitlements, balances, invoice line items — is rounded half-up to 2 decimal places at the step where the specification says it is rounded. Invoice totals are built per line: each line item is first rounded half-up to cents, and the invoice total is the sum of those already-rounded lines, never a single rounding applied to an unrounded sum.

Timestamps that define delivery windows and maintenance windows are half-open intervals: the window includes its start instant and excludes its end instant. Two windows whose boundary instants merely touch — one ending exactly when the next begins — are adjacent, not overlapping. All interval comparisons in this system are made to the second.

### 2.5. The Logical Clock

The district does not consult wall-clock time. A logical clock governs every time-sensitive decision: whether a maintenance window may be activated, whether a rider may open a turnout, and whether an issued invoice has crossed its delinquency threshold. At server startup, before any test-driving call is made, the logical clock reads exactly 2026-08-01T00:00:00Z. A `DistrictAdmin` advances it through an admin-only capability that sets the clock to a supplied `to_iso8601` instant; the response echoes the resulting `current_utc`. Once advanced, the clock never falls back to wall-clock time on its own.

### 2.6. Optimistic Concurrency Control

Two write operations accept an explicit expected-version field and reject callers whose view of the parent ledger is stale.

Placing a turnout order must carry `expected_water_account_version` equal to the current `version` of the referenced `WaterAccount`. If the account's version has advanced since the client last read it — for example because another order was created against the account or a lien transition touched it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing water against an account state it has not observed.

Requesting a transfer must carry `expected_source_allocation_version` equal to the current `version` of the source `SeasonAllocation`. A mismatch with the source allocation's current version is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes an expected-version field.

### 2.7. Validation Priority Order

When several checks could fail on the same request, the server reports the first failure in this fixed evaluation order:

1. **Authentication** — the two headers are present and the role is declared, else `ERR_UNAUTHENTICATED`.
2. **Request shape** — required fields present, types valid, enum values within their declared sets, numbers positive where constrained, and end timestamps strictly after start timestamps, else `ERR_INVALID_REQUEST`. The transfer rule that `to_account_id` must differ from `from_account_id` is a shape rule enforced here.
3. **Authorization and ownership** — the role is permitted for the endpoint and any ownership check passes, else `ERR_FORBIDDEN`.
4. **Existence** — referenced resources exist, path identifiers checked left-to-right first, then body foreign-key fields in their declared input order, else `ERR_NOT_FOUND`.
5. **Stale version** — the optimistic-concurrency checks of §2.6, else `ERR_STALE_VERSION`.
6. **Lifecycle state** — the target entity is in a valid from-state for the transition and cross-entity state gates hold (account `ACTIVE`, season `OPEN`, reach `IN_SERVICE`), else the appropriate `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_SEASON_NOT_OPEN`, or `ERR_INVALID_*_STATE` code.
7. **Drought freeze** — no transfer may be created, approved, or posted while a drought declaration is `EFFECTIVE` on the season, else `ERR_TRANSFER_BLOCKED_DROUGHT`.
8. **Temporal conflicts** — window-vs-order conflicts, turnaround gaps, and clock-window checks, else the appropriate 422 code.
9. **Uniqueness and capacity** — duplicate season years, duplicate allocations or invoices per (account, season), and reach instantaneous capacity, else the appropriate 409 or 422 code.
10. **Sufficient water** — the quantity requested fits within the available balance, else `ERR_INSUFFICIENT_ALLOCATION`.

### 2.8. Water Measurement Constants

Flows are requested and measured in cubic feet per second, durations in hours, and volumes in acre-feet. One cubic foot per second sustained for one hour yields 0.0826 acre-feet; this conversion factor is applied identically when computing the volume an order requests and the volume a rider's measurement represents, each result rounded half-up to 2 decimal places.

Turnout orders placed by the same account must respect a turnaround gap: between any two non-terminal orders of the same account, the gap between their delivery windows must be at least 6 hours; a gap of exactly 6 hours is permitted. The delinquency grace period for assessments is 10 days beyond the due date, and the late penalty rate is 10 percent of the sum of the invoice's acreage and toll lines.

### 2.9. Priority Classes and Drought Stages

Each account's seniority derives from its water right's priority date. An account whose `water_right_priority_date` falls on or before 1914-12-31 is classed `SENIOR`; any later date is classed `JUNIOR`. This class is computed once when the account is created and pinned on the account as `priority_class`.

Drought curtailment is declared in three stages, each pinning a pair of percentages applied to the base entitlement — one percentage for senior accounts and one for junior accounts. Stage 1 curtails seniors by 0 percent and juniors by 15 percent. Stage 2 curtails seniors by 10 percent and juniors by 40 percent. Stage 3 curtails seniors by 25 percent and juniors by 75 percent. When a declaration is proposed, the pair for its stage is recorded on the declaration as `senior_curtailment_pct` and `junior_curtailment_pct`; when it is effectuated, each allocation's curtailed entitlement is its base entitlement reduced by the percentage matching its account's priority class, rounded half-up to 2 decimal places.

## 3. Business Logic & Workflows

### 3.1. Onboarding Accounts and Standing Up a Season

A district administrator onboards each irrigator by creating a water account with the holder's `holder_name`, the `parcel_number` of the served parcel, the `irrigated_acres` under irrigation (which must be greater than zero), and the `water_right_priority_date` of the account's water right. The account is born `ACTIVE`, its `priority_class` is derived from the priority date per §2.9, and it immediately participates in every ownership check that `WaterUser` callers will later face.

Seasons follow their own lifecycle. An administrator creates an `IrrigationSeason` by supplying the calendar `year` (which must be unique across seasons — a duplicate year is refused with `ERR_DUPLICATE_SEASON_YEAR`), the board-announced `announced_af_per_acre` (greater than zero), the `carryover_cap_pct` (between 0 and 100 inclusive) bounding how much unused water may roll into the following season, the `billing_method` (either `PER_ACRE` or `PER_AF_DELIVERED`), the `assessment_rate_per_acre`, the three toll parameters `toll_tier1_cap_af`, `toll_tier1_rate_per_af`, and `toll_tier2_rate_per_af`, the `overage_rate_per_af` applied to deliveries beyond entitlement, and the season's `start_date` and `end_date` (the start must be strictly before the end). All rate fields are non-negative. A new season is born `DRAFT`. Announcing the season moves it `DRAFT → ANNOUNCED`, and opening it moves it `ANNOUNCED → OPEN`; each transition bumps the season's `version`. Attempting these transitions from a wrong from-state — opening a season still in `DRAFT`, for instance — is rejected with `ERR_INVALID_SEASON_STATE`.

Once a season is `ANNOUNCED` or `OPEN`, the administrator may create a `SeasonAllocation` pairing a `water_account_id` with a `season_id`. Only one allocation may exist per account-season pair; a second attempt is refused with `ERR_DUPLICATE_ALLOCATION`. At creation the allocation's `base_entitlement_af` is computed as the account's `irrigated_acres` multiplied by the season's `announced_af_per_acre`, rounded half-up to 2 decimal places. The allocation's `carryover_in_af` is read from the account's allocation in the most recent closed prior season — the closed season with the greatest `year` strictly less than the new season's year — taking that prior allocation's `carryover_out_af`; when no such prior closed allocation exists, `carryover_in_af` is 0.00. The new allocation is born `ACTIVE` with `curtailed_entitlement_af` null and `effective_entitlement_af` reading the base value.

### 3.2. The Allocation Ledger: Committed, Delivered, and Available Water

Each `SeasonAllocation` is a running ledger whose derived quantities are recomputed on every mutation that touches it — order creation, cancellation, rejection, measurement verification, transfer posting, drought effectuation or lifting, and account acreage changes. The ledger's reads:

- `committed_af` sums `requested_quantity_af` over the allocation's orders whose status is `REQUESTED`, `SCHEDULED`, or `FLOWING` — water reserved but not yet delivered.
- `delivered_af` sums `measured_af` over verified work orders belonging to this allocation's delivered orders; only verified measurements count.
- `transfers_in_af` and `transfers_out_af` sum `quantity_af` over posted transfer requests into and out of this account for this season.
- `available_af` is the entitlement pool — `effective_entitlement_af` plus `carryover_in_af` plus `transfers_in_af` minus `transfers_out_af` — with `delivered_af` and `committed_af` both subtracted. This net-of-committed reading is the balance that order creation and transfer approval/posting are checked against.
- `over_allocated_af` is the amount by which `delivered_af` exceeds that same entitlement pool (ignoring committed water entirely), floored at zero.

The entitlement pool appears in two readings. The net-of-committed reading governs order placement and transfer checks. A delivered-only reading — which ignores committed water and nets the entitlement pool against measured deliveries alone — governs the carryover computation at season close, so a season that ends with a still-pending order reports a larger unused balance than the net-of-committed reading would show for identical data.

### 3.3. Placing and Scheduling Turnout Orders

An irrigator places an order by naming the `water_account_id` (which must be their own account), the `season_allocation_id` the order will reserve against, the `canal_reach_id` serving their turnout, a `requested_cfs` flow greater than zero, and a delivery window from `requested_start_at` to `requested_end_at` with the start strictly before the end. The create must also carry `expected_water_account_version` per §2.6. At creation the order's `requested_quantity_af` is computed: the window's length in hours — the difference between `requested_end_at` and `requested_start_at` measured in seconds and divided by 3600 — is multiplied by `requested_cfs` and by the 0.0826 conversion factor, and the product is rounded half-up to 2 decimal places. That quantity is immediately committed: it is added to the allocation's `committed_af`, the account's `version` increments by 1, and the order is born `REQUESTED`.

Creation is refused when the account is not `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`), when the season is not `OPEN` (`ERR_SEASON_NOT_OPEN`), when the window fails the turnaround-gap rule against the account's other non-terminal orders (`ERR_ORDER_TURNAROUND_CONFLICT`), or when `requested_quantity_af` exceeds the allocation's `available_af` on the net-of-committed reading (`ERR_INSUFFICIENT_ALLOCATION`).

Scheduling is the administrator's act of placing a `REQUESTED` order onto the rotation, and it carries the heaviest gate set in the system. The administrator names the `rider_user_id` of the ditch rider who will perform the measurement. Scheduling re-checks that the account is `ACTIVE` and the season `OPEN`, then verifies the delivery window against the reach: no `PLANNED` or `ACTIVE` maintenance window on that reach may overlap the order's half-open window, else `ERR_WINDOW_TIME_CONFLICT`. Capacity is then enforced instant-by-instant: at every instant of the requested window, the sum of `requested_cfs` over the reach's other `SCHEDULED` or `FLOWING` orders overlapping that instant, plus this order's own `requested_cfs`, must not exceed the reach's `max_capacity_cfs`, else `ERR_REACH_CAPACITY_EXCEEDED`. The turnaround rule is re-evaluated at scheduling as well: no other non-terminal order of the same account may overlap this window, and the gap to every adjacent such order must be at least 6 hours (`ERR_ORDER_TURNAROUND_CONFLICT`). When all gates pass, the order moves `REQUESTED → SCHEDULED` and a `RiderWorkOrder` is created in one stroke — its `turnout_order_id` pointing at this order, its `rider_user_id` taken from the scheduling input, its status `ASSIGNED`.

An order that will not be served is disposed of in two ways. An administrator may reject a `REQUESTED` order, moving it `REQUESTED → REJECTED`; alternatively, the administrator or the owning irrigator may cancel a `REQUESTED` or `SCHEDULED` order, moving it to `CANCELLED`. Both paths release the order's `requested_quantity_af` from the allocation's `committed_af`, and cancelling a `SCHEDULED` order additionally cascades `CANCELLED` onto its linked work order when that work order is still `ASSIGNED` or `IN_PROGRESS`. Terminal orders (`DELIVERED`, `CANCELLED`, `REJECTED`) accept no further transitions; attempts to schedule a non-`REQUESTED` order or cancel a terminal one are refused with `ERR_INVALID_ORDER_STATE`.

### 3.4. Field Delivery: The Rider's Start, Measurement, and District Verification

When the scheduled window arrives, the assigned ditch rider opens the turnout. Starting the order is permitted only to the rider whose `X-User-ID` equals the linked work order's `rider_user_id` — any other caller receives `ERR_FORBIDDEN`. Two further gates apply: the reach must be `IN_SERVICE` (a start attempted while the reach is `SHUTDOWN` is refused with `ERR_INVALID_ORDER_STATE`), and the logical clock must fall within the order's half-open window — at or after `requested_start_at` and strictly before `requested_end_at` — else `ERR_OUTSIDE_DELIVERY_WINDOW`. A successful start moves the order `SCHEDULED → FLOWING` and advances the linked work order `ASSIGNED → IN_PROGRESS` in the same act.

After the run, the assigned rider submits the measurement: `measured_cfs` and `measured_hours`, each greater than zero. Submitting transitions the work order `IN_PROGRESS → MEASUREMENT_SUBMITTED` and stores the computed `measured_af` — `measured_cfs` multiplied by `measured_hours` multiplied by 0.0826, rounded half-up to 2 decimal places. A submission from any caller other than the assignee is refused with `ERR_FORBIDDEN`; a submission attempted before the work order has started is refused with `ERR_INVALID_WORK_ORDER_STATE`.

The district administrator then adjudicates the submission. Verifying the measurement moves the work order `MEASUREMENT_SUBMITTED → VERIFIED` and, in the same stroke, delivers the turnout order: the order moves `FLOWING → DELIVERED`, its `actual_delivered_af` (null until this moment) is set to the verified `measured_af`, and its `over_delivered` flag is set true exactly when the measured volume exceeds the order's `requested_quantity_af`. The allocation ledger posts the delivery: `measured_af` is added to `delivered_af` while the order's `requested_quantity_af` is released from `committed_af`. Alternatively, the administrator may return the measurement for rework, moving the work order `MEASUREMENT_SUBMITTED → IN_PROGRESS`: the submitted `measured_cfs`, `measured_hours`, and `measured_af` are cleared to null, the supplied `return_reason` is recorded, and — notably — the linked turnout order remains `FLOWING` while the rider re-measures. Verifying twice, or verifying a work order that has not reached `MEASUREMENT_SUBMITTED`, is refused with `ERR_INVALID_WORK_ORDER_STATE`.

### 3.5. Canal Reaches and Maintenance Shutdowns

Each canal reach is registered with a `name` and a `max_capacity_cfs` greater than zero, and is born `IN_SERVICE`. Maintenance is scheduled by planning a window on the reach: the administrator supplies the `canal_reach_id`, a `start_at` and `end_at` with the start strictly before the end, and an optional free-text `reason`. Planning rejects any new window that overlaps an existing `PLANNED` or `ACTIVE` window on the same reach — `ERR_WINDOW_OVERLAP` — under half-open semantics in which a new window beginning exactly when an existing one ends is adjacent and allowed; windows already `COMPLETED` or `CANCELLED` impose no constraint. A planned window is born `PLANNED` and may be cancelled while still `PLANNED`, moving it to `CANCELLED`.

Activating a window is permitted only while the logical clock sits inside the window's half-open period, else `ERR_WINDOW_OUT_OF_PERIOD`. Activation moves the window `PLANNED → ACTIVE` and flips the reach to `SHUTDOWN`. The shutdown is not merely a label: every `SCHEDULED` turnout order on that reach whose delivery window overlaps the activated window is cascade-cancelled, each cancellation releasing its `requested_quantity_af` from its allocation's `committed_af` and cancelling the order's non-terminal rider work order. Completing an `ACTIVE` window moves it `ACTIVE → COMPLETED` and returns the reach to `IN_SERVICE` — but only when no other `ACTIVE` window remains on that reach. Window transitions from wrong from-states, such as activating twice or completing a still-`PLANNED` window, are refused with `ERR_INVALID_WINDOW_STATE`.

### 3.6. Transfers of Allocation Between Accounts

Irrigators may lease allocation to one another within a season. The source account's owner initiates a transfer by naming `from_account_id` (their own account — any other value fails ownership with `ERR_FORBIDDEN`), `to_account_id` (which must differ from the source; this is a request-shape rule), the `season_id`, and a `quantity_af` greater than zero, and the create must carry `expected_source_allocation_version` per §2.6. A transfer is born `PENDING`; its creation increments the source allocation's `version` by 1. Creation requires both accounts `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`), the season `OPEN` (else `ERR_SEASON_NOT_OPEN`), no `EFFECTIVE` drought declaration on the season (else `ERR_TRANSFER_BLOCKED_DROUGHT`), and a source `available_af` on the net-of-committed reading at least equal to `quantity_af` (else `ERR_INSUFFICIENT_ALLOCATION`).

Approval and posting are separate administrative acts, and each re-evaluates every substantive gate rather than trusting the earlier check. Approving a `PENDING` transfer re-verifies that both accounts are still `ACTIVE`, that the season remains `OPEN`, that no drought declaration has become `EFFECTIVE`, and that the source allocation's `available_af` still covers `quantity_af`, moving the transfer `PENDING → APPROVED`. Posting an `APPROVED` transfer repeats the account-active check, the drought freeze, and the source-balance check one final time — a balance that sufficed at approval may no longer suffice at posting if intervening orders have committed water — and on success moves the transfer `APPROVED → POSTED` while mutating both ledgers in one stroke: `quantity_af` is added to the source allocation's `transfers_out_af` and to the destination allocation's `transfers_in_af`, and both allocations' `version` values increment by 1.

An administrator may reject a `PENDING` or `APPROVED` transfer, moving it to `REJECTED`; the source account's owner may cancel a `PENDING` or `APPROVED` transfer, moving it to `CANCELLED` (ownership enforced with `ERR_FORBIDDEN`). Transfers in terminal states — `POSTED`, `REJECTED`, `CANCELLED` — accept no further transitions; posting a `PENDING` transfer or approving a `POSTED` one is refused with `ERR_INVALID_TRANSFER_STATE`.

### 3.7. Drought Curtailment and Its Cascades

When supply falls short, the board acts through a drought declaration. An administrator proposes a declaration by naming the `season_id` and a `stage` of `STAGE_1`, `STAGE_2`, or `STAGE_3`; the declaration records the stage's pinned percentages as `senior_curtailment_pct` and `junior_curtailment_pct` per §2.9 and is born `PROPOSED`.

Effectuating a `PROPOSED` declaration requires the season to be `OPEN` (else `ERR_SEASON_NOT_OPEN`) and requires that no other declaration on the season is currently `EFFECTIVE` (else `ERR_INVALID_DROUGHT_STATE`). Effectuation moves the declaration `PROPOSED → EFFECTIVE` and propagates curtailment through every allocation of the season: each allocation's `curtailed_entitlement_af` is computed as its `base_entitlement_af` reduced by the percentage matching its account's priority class — rounded half-up to 2 decimal places — its `effective_entitlement_af` switches to the curtailed value, and its status becomes `CURTAILED`.

The curtailment cascade then restores ledger feasibility. For each allocation whose `committed_af` now exceeds its recomputed `available_af`, the system cancels that allocation's orders in `REQUESTED` or `SCHEDULED` status, selecting them in descending `requested_start_at` order — latest-starting first — with ties broken by `created_at` descending, and continues cancelling until `committed_af` no longer exceeds `available_af`. Each cancelled order releases its committed water from the allocation and cascades `CANCELLED` onto its non-terminal rider work order.

Lifting an `EFFECTIVE` declaration moves it `EFFECTIVE → LIFTED`: every `CURTAILED` allocation of the season has its `effective_entitlement_af` restored to `base_entitlement_af` and its status returned to `ACTIVE`. Orders cancelled by the curtailment cascade are not resurrected — they remain `CANCELLED`. Effectuating a declaration that is not `PROPOSED`, or acting on a declaration from any other wrong from-state, is refused with `ERR_INVALID_DROUGHT_STATE`. While any declaration is `EFFECTIVE` on a season, the transfer freeze of §3.6 applies to transfer creation, approval, and posting alike.

### 3.8. Assessment Billing, Delinquency, and Liens

The district bills each account once per season. An administrator creates an `AssessmentInvoice` naming the `water_account_id` and `season_id`; only one invoice may exist per account-season pair (a duplicate is refused with `ERR_DUPLICATE_INVOICE`). At creation the season's `billing_method` is copied onto the invoice as `billing_method_snapshot`, and the line items are computed according to that snapshot.

Under `PER_ACRE` billing, the `acreage_line_amount` is the account's `irrigated_acres` multiplied by the season's `assessment_rate_per_acre`, rounded half-up to 2 decimal places, and the `toll_line_amount` is 0.00. Under `PER_AF_DELIVERED` billing, the `acreage_line_amount` is 0.00 and the `toll_line_amount` is the tiered water toll on the allocation's season-to-date `delivered_af`: the delivered volume is split into a tier-1 portion up to the season's `toll_tier1_cap_af` billed at `toll_tier1_rate_per_af`, a tier-2 portion above that cap billed at `toll_tier2_rate_per_af`, and an overage portion — the amount by which delivered volume exceeds the entitlement pool of effective entitlement plus carryover-in plus transfers-in minus transfers-out — billed at `overage_rate_per_af`; the three products are summed and the result is rounded half-up to 2 decimal places. The rounding order is pinned: each line is rounded to cents first, and the invoice's `total_amount` is the sum of the rounded lines. The `penalty_line_amount` begins at 0.00, and `issued_at` and `paid_at` are null while the invoice is `DRAFT`. The two methods are mutually exclusive views of the same account: identical delivery data yields a different total under `PER_ACRE` than under `PER_AF_DELIVERED`.

Issuing a `DRAFT` invoice moves it `DRAFT → ISSUED`, stamps `issued_at` from the logical clock, and stores the administrator-supplied `due_date`. From then on the delinquency sweep governs: an administrator may run the sweep for a season, and every invoice of that season still in `ISSUED` whose due date plus the 10-day grace period is strictly before the logical clock flips to `DELINQUENT` — an invoice whose grace period expires exactly at the current clock instant remains `ISSUED`, since the comparison is strict. `DRAFT`, `PAID`, and `LIEN_FILED` invoices are never touched by the sweep. The sweep's response reports the `swept_count` and the list `delinquent_invoice_ids`. Flipping to `DELINQUENT` recomputes the `penalty_line_amount` as 10 percent of the sum of the (already rounded) acreage and toll lines, itself rounded half-up to 2 decimal places, and `total_amount` is recomputed as the sum of the rounded lines including the penalty.

The account owner pays an invoice in full from `ISSUED`, `DELINQUENT`, or `LIEN_FILED`; the payment is authorized by matching the caller's `X-User-ID` to the invoice's `water_account_id` (else `ERR_FORBIDDEN`) and stamps `paid_at` from the logical clock. Paying from `ISSUED` or `DELINQUENT` simply moves the invoice to `PAID`. Paying a `LIEN_FILED` invoice additionally releases the lien hold: if no other `LIEN_FILED` invoice remains for the account, the account's status returns to `ACTIVE` and its `version` increments by 1.

When a delinquent invoice remains unpaid, the administrator files a lien, moving the invoice `DELINQUENT → LIEN_FILED`. Filing a lien suspends the account: the account's status becomes `SUSPENDED` and its `version` increments by 1. A `SUSPENDED` account is barred from new turnout orders and new transfer requests — order creation and scheduling, and transfer creation, approval, and posting, all fail with `ERR_ACCOUNT_NOT_ACTIVE` while the hold stands. Invoice transitions from wrong from-states — paying a `DRAFT` invoice, filing a lien on a merely `ISSUED` one, or paying an already `PAID` invoice — are refused with `ERR_INVALID_INVOICE_STATE`.

### 3.9. Closing Accounts and Closing the Season

An administrator may close an account from `ACTIVE` or `SUSPENDED`, moving it to the terminal `CLOSED` state and incrementing its `version` by 1. Closure is refused with `ERR_INVALID_ACCOUNT_STATE` while the account has any turnout order in `REQUESTED`, `SCHEDULED`, or `FLOWING`, or any transfer request in `PENDING` or `APPROVED`.

Closing the season is the district's end-of-year settlement, permitted only when no order of the season is still `FLOWING` (else `ERR_INVALID_SEASON_STATE`). The close fans out across the season's records in one act. Every order still `REQUESTED` or `SCHEDULED` is moved to `CANCELLED`, releasing its `requested_quantity_af` from its allocation's `committed_af`, and each such order's non-terminal rider work order is cancelled alongside it. Every allocation of the season — whether `ACTIVE` or `CURTAILED` — moves to `CLOSED` and has its `carryover_out_af` settled. The settlement takes the delivered-only reading: the settled-unused water is the entitlement pool (effective entitlement, carryover-in, and transfers-in, minus transfers-out) net of `delivered_af` alone, floored at zero, and the cap is the allocation's `base_entitlement_af` multiplied by the season's `carryover_cap_pct` and divided by 100, rounded half-up to 2 decimal places. An account that closed the season over-allocated — delivered water exceeding the entitlement pool — forfeits carryover entirely and its `carryover_out_af` is 0.00; otherwise `carryover_out_af` is the lesser of the settled-unused water and the cap, with an unused balance exactly equal to the cap carrying over the full cap amount. The season itself moves `OPEN → CLOSED` and its `version` increments by 1. A closed season's `carryover_out_af` values are exactly what the next season's allocation creation reads as `carryover_in_af`, per §3.1.

## 4. Endpoint Definitions

All endpoints are mounted under the API root; district resources live under `/district`. Creating a new resource returns HTTP 201 with the created resource; all other successful operations — reads, state transitions, payments, sweeps — return HTTP 200. Error responses follow §2.2 and carry the error codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server's logical clock to a supplied `to_iso8601` instant; startup default is exactly 2026-08-01T00:00:00Z | DistrictAdmin |
| POST | /district/water-accounts | Create a water account with its water-right priority date | DistrictAdmin |
| GET | /district/water-accounts | List water accounts (filterable by `status`) | DistrictAdmin, WaterUser, DitchRider |
| GET | /district/water-accounts/{id} | Get one water account | DistrictAdmin, WaterUser, DitchRider |
| POST | /district/water-accounts/{id}/close | Close an account (ACTIVE/SUSPENDED → CLOSED, terminal) | DistrictAdmin |
| POST | /district/seasons | Create an irrigation season with announced allocation and billing configuration | DistrictAdmin |
| GET | /district/seasons | List irrigation seasons (filterable by `status`) | DistrictAdmin, WaterUser, DitchRider |
| GET | /district/seasons/{id} | Get one irrigation season | DistrictAdmin, WaterUser, DitchRider |
| POST | /district/seasons/{id}/announce | Announce the season (DRAFT → ANNOUNCED) | DistrictAdmin |
| POST | /district/seasons/{id}/open | Open the season for ordering (ANNOUNCED → OPEN) | DistrictAdmin |
| POST | /district/seasons/{id}/close | Close the season: cancels non-terminal orders and work orders, closes allocations with carryover settled | DistrictAdmin |
| POST | /district/seasons/{id}/run-delinquency-sweep | Flip qualifying ISSUED invoices of the season to DELINQUENT with penalty applied | DistrictAdmin |
| POST | /district/season-allocations | Create a season allocation for an account; computes base entitlement and carryover-in | DistrictAdmin |
| GET | /district/season-allocations | List season allocations (filterable by `water_account_id`, `season_id`, `status`) | DistrictAdmin, WaterUser, DitchRider |
| GET | /district/season-allocations/{id} | Get one season allocation | DistrictAdmin, WaterUser, DitchRider |
| POST | /district/turnout-orders | Place a water order; computes the requested quantity and commits it against the allocation (OCC on the account) | WaterUser |
| GET | /district/turnout-orders | List turnout orders (filterable by `water_account_id`, `season_allocation_id`, `canal_reach_id`, `status`) | DistrictAdmin, WaterUser, DitchRider |
| GET | /district/turnout-orders/{id} | Get one turnout order | DistrictAdmin, WaterUser, DitchRider |
| POST | /district/turnout-orders/{id}/schedule | Schedule a REQUESTED order onto the rotation; creates the rider work order | DistrictAdmin |
| POST | /district/turnout-orders/{id}/reject | Reject a REQUESTED order, releasing its committed water | DistrictAdmin |
| POST | /district/turnout-orders/{id}/cancel | Cancel a REQUESTED or SCHEDULED order, releasing committed water and cancelling its work order | DistrictAdmin, WaterUser |
| POST | /district/turnout-orders/{id}/start | Assigned rider opens the turnout (SCHEDULED → FLOWING); work order goes IN_PROGRESS | DitchRider |
| GET | /district/rider-work-orders | List rider work orders (filterable by `turnout_order_id`, `rider_user_id`, `status`) | DistrictAdmin, DitchRider |
| GET | /district/rider-work-orders/{id} | Get one rider work order | DistrictAdmin, DitchRider |
| POST | /district/rider-work-orders/{id}/submit-measurement | Assigned rider submits the turnout measurement | DitchRider |
| POST | /district/rider-work-orders/{id}/verify | Verify a submitted measurement; delivers the order and posts measured water | DistrictAdmin |
| POST | /district/rider-work-orders/{id}/return | Return a submitted measurement for rework; clears measured values | DistrictAdmin |
| POST | /district/assessment-invoices | Create the season's assessment invoice for an account (DRAFT) | DistrictAdmin |
| GET | /district/assessment-invoices | List assessment invoices (filterable by `water_account_id`, `season_id`, `status`) | DistrictAdmin, WaterUser |
| GET | /district/assessment-invoices/{id} | Get one assessment invoice | DistrictAdmin, WaterUser |
| POST | /district/assessment-invoices/{id}/issue | Issue a DRAFT invoice; stamps issued-at and stores the due date | DistrictAdmin |
| POST | /district/assessment-invoices/{id}/pay | Pay an invoice in full from ISSUED, DELINQUENT, or LIEN_FILED | WaterUser |
| POST | /district/assessment-invoices/{id}/file-lien | File a lien on a DELINQUENT invoice; suspends the account | DistrictAdmin |
| POST | /district/canal-reaches | Create a canal reach with its maximum carrying capacity | DistrictAdmin |
| GET | /district/canal-reaches | List canal reaches (filterable by `status`) | DistrictAdmin, WaterUser, DitchRider |
| GET | /district/canal-reaches/{id} | Get one canal reach | DistrictAdmin, WaterUser, DitchRider |
| POST | /district/maintenance-windows | Plan a maintenance shutdown window on a reach | DistrictAdmin |
| GET | /district/maintenance-windows | List maintenance windows (filterable by `canal_reach_id`, `status`) | DistrictAdmin, WaterUser, DitchRider |
| GET | /district/maintenance-windows/{id} | Get one maintenance window | DistrictAdmin, WaterUser, DitchRider |
| POST | /district/maintenance-windows/{id}/activate | Activate a PLANNED window; shuts the reach and cascade-cancels overlapping SCHEDULED orders | DistrictAdmin |
| POST | /district/maintenance-windows/{id}/complete | Complete an ACTIVE window; returns the reach to service when no other ACTIVE window remains | DistrictAdmin |
| POST | /district/maintenance-windows/{id}/cancel | Cancel a PLANNED window | DistrictAdmin |
| POST | /district/transfer-requests | Request a transfer of allocation between two accounts in the same season (OCC on the source allocation) | WaterUser |
| GET | /district/transfer-requests | List transfer requests (filterable by `from_account_id`, `to_account_id`, `season_id`, `status`) | DistrictAdmin, WaterUser |
| GET | /district/transfer-requests/{id} | Get one transfer request | DistrictAdmin, WaterUser |
| POST | /district/transfer-requests/{id}/approve | Approve a PENDING transfer after re-checking account states, drought freeze, and source balance | DistrictAdmin |
| POST | /district/transfer-requests/{id}/post | Post an APPROVED transfer to both allocations' ledgers | DistrictAdmin |
| POST | /district/transfer-requests/{id}/reject | Reject a PENDING or APPROVED transfer | DistrictAdmin |
| POST | /district/transfer-requests/{id}/cancel | Source-account owner cancels a PENDING or APPROVED transfer | WaterUser |
| POST | /district/drought-declarations | Propose a drought curtailment declaration for a season | DistrictAdmin |
| GET | /district/drought-declarations | List drought declarations (filterable by `season_id`, `status`) | DistrictAdmin, WaterUser |
| GET | /district/drought-declarations/{id} | Get one drought declaration | DistrictAdmin, WaterUser |
| POST | /district/drought-declarations/{id}/effectuate | Effectuate a PROPOSED declaration; curtails all season allocations and cascade-cancels over-committed orders | DistrictAdmin |
| POST | /district/drought-declarations/{id}/lift | Lift an EFFECTIVE declaration; restores full entitlements | DistrictAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_INVALID_REQUEST | 400 |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_SEASON_NOT_OPEN | 409 |
| ERR_INVALID_ACCOUNT_STATE | 409 |
| ERR_INVALID_SEASON_STATE | 409 |
| ERR_INVALID_ORDER_STATE | 409 |
| ERR_INVALID_WORK_ORDER_STATE | 409 |
| ERR_INVALID_INVOICE_STATE | 409 |
| ERR_INVALID_WINDOW_STATE | 409 |
| ERR_INVALID_TRANSFER_STATE | 409 |
| ERR_INVALID_DROUGHT_STATE | 409 |
| ERR_TRANSFER_BLOCKED_DROUGHT | 409 |
| ERR_WINDOW_TIME_CONFLICT | 422 |
| ERR_ORDER_TURNAROUND_CONFLICT | 422 |
| ERR_WINDOW_OUT_OF_PERIOD | 422 |
| ERR_OUTSIDE_DELIVERY_WINDOW | 422 |
| ERR_WINDOW_OVERLAP | 422 |
| ERR_REACH_CAPACITY_EXCEEDED | 422 |
| ERR_DUPLICATE_SEASON_YEAR | 409 |
| ERR_DUPLICATE_ALLOCATION | 409 |
| ERR_DUPLICATE_INVOICE | 409 |
| ERR_INSUFFICIENT_ALLOCATION | 422 |
