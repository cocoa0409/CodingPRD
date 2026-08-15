# Net Metering Interconnection API — Product Requirements Document

## 1. Introduction

Utilities that offer net metering must process a steady stream of distributed generation interconnection requests against a finite, closely watched pool of circuit capacity. Each request touches many hands: the customer who proposes a solar array, wind turbine, or fuel cell; the interconnection coordinator who screens paperwork; the distribution engineer who studies transformer and feeder loading; the meter crew that swaps in a bidirectional meter; and the inspector who signs off before the utility grants permission to operate. Along the way the utility must enforce program-wide capacity caps, maintain a fair first-come queue when capacity runs short, issue upgrade cost estimates with firm validity windows, and keep an auditable record of who approved what.

Once energized, the relationship continues for the life of the account. Every billing period the utility nets imported and exported energy under one of two metering variants — banking surplus kilowatt-hours for later use, or converting surplus to a monetary credit at an export rate — and once a year it settles up: cashing out or rolling over the accumulated surplus according to the program's true-up mode. This document specifies the API that backs that entire desk, from program configuration and grid topology registration through application intake, technical screening, supplemental review, upgrade costing, field work, energization, metering, and annual reconciliation.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six distinct roles: `Applicant`, `InterconnectionCoordinator`, `DistributionEngineer`, `MeterTechnician`, `Inspector`, and `ProgramAdministrator`. A request missing either header, or carrying a role name that is not one of these six, is rejected with `ERR_MISSING_CONTEXT_HEADER` (HTTP 401). Access to specific operations is restricted by role per the endpoint table in §4; an authenticated user who attempts an operation outside their role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that traces back to a customer compare the owning service account's `customer_id` field to `X-User-ID`. An `Applicant` may create applications only against accounts they own, and may drive only their own applications, documents, inspections, and cost-estimate decisions; a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `InterconnectionCoordinator`, `DistributionEngineer`, `MeterTechnician`, `Inspector`, or `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `inspector_user_id` on an inspection or `technician_user_id` on a meter exchange) but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and the Expiry Sweep

All time-dependent rules in this document — reservation expiries, estimate validity windows, inspection timestamps, tariff effectiveness, reconciliation windows — evaluate against a single server-held logical clock, never against wall-clock time. Before any client call is made, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ProgramAdministrator` may advance the clock by supplying a `to_iso8601` instant; the clock endpoint returns the new `current_utc`, and any role may read `current_utc` at any time. Advancing the clock performs no automatic expirations: time-based state changes happen only through an explicit expiry sweep.

The sweep is a `ProgramAdministrator`-initiated, per-program operation that processes expirations in a pinned order. First, every still-`ISSUED` upgrade cost estimate of the program whose `valid_until` is earlier than the current clock time is expired; each affected application is withdrawn with `withdrawal_reason` `ESTIMATE_EXPIRED`, processed in ascending order of the application's `created_at`. Second, every application of the program still holding a reservation whose `reservation_expires_at` is earlier than the current clock time is withdrawn with `withdrawal_reason` `RESERVATION_EXPIRED`, again in ascending `created_at` order. Third, the freed capacity triggers the queue promotion scan described in §3.3. Fourth, the program's capacity posture is recomputed per §2.7.

### 2.5. Common Resource Properties

All primary resources — programs, tariff schedules, feeders, service transformers, customers, service accounts, applications, documents, screening reports, supplemental reviews, cost estimates, inspections, meter exchanges, meter readings, and annual reconciliations — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments with every modification to the resource.

The credit ledger is the deliberate exception: a `CreditLedgerEntry` is immutable and append-only, so it carries only `id` and `created_at` — both `updated_at` and `version` are absent. Ledger entries are never deleted; corrections are expressed by appending compensating entries (see §2.8).

### 2.6. Units, Precision, and Rounding

All power figures (system sizes, capacity caps, nameplates, peak loads, reserved and interconnected watts) are integer watts AC. All energy figures (usage, production estimates, imports, exports, banked energy) are integer watt-hours. All money is integer cents; rates are integer millicents per kilowatt-hour. To convert an energy quantity in watt-hours to cents at a rate in millicents per kilowatt-hour, multiply the watt-hours by the rate and divide by one million — one thousand watt-hours per kilowatt-hour times one thousand millicents per cent — rounding half-up to whole cents.

Rounding is pinned to the posting moment: every credit ledger entry's `amount_cents` is rounded half-up to whole cents when the entry is posted, and account balances are sums of those already-rounded posted entries, so no sub-cent remainder ever carries forward. Upgrade cost estimates are the one multi-step computation, and they round exactly once, at the very end (see §3.5). Percentage-derived watt limits (the transformer and feeder screens, and the size-to-load eligibility cap) use integer arithmetic with a floor on the percentage product.

### 2.7. The Program Capacity Ledger and Posture

Each program tracks a live capacity budget in watts. The program's `available_capacity_watts` is its `aggregate_cap_watts` minus its `interconnected_watts` minus its `reserved_watts`, where `interconnected_watts` is the sum of `system_size_watts_ac` over the program's applications that have reached `PTO_GRANTED` or `OPERATING`, and `reserved_watts` is the sum of `capacity_reserved_watts` over applications currently holding a reservation. The program's `queued_count` is the number of its applications sitting in `WAITING_FOR_CAPACITY`. All four figures are computed by the server, start at zero (with `available_capacity_watts` starting at the full cap), and move only as side effects of the workflows in §3.

After any mutation that changes the reservation or interconnected totals, the program's posture is recomputed: if `available_capacity_watts` has fallen to zero or below, a program in `OPEN` moves to `CAP_REACHED`; if it has risen above zero, a program in `CAP_REACHED` returns to `OPEN`. The posture is a signal visible to clients — by itself it blocks nothing, and submissions remain welcome while the program is `OPEN` or `CAP_REACHED`. A `ProgramAdministrator` may also suspend intake (moving the program to `SUSPENDED`, which rejects new submissions), resume it (returning to `OPEN` if capacity is available, otherwise landing directly in `CAP_REACHED`), or close it (`CLOSED`, terminal) once no application of the program remains in a non-terminal status.

### 2.8. The Append-Only Credit Ledger

Every monetary or energy-bank movement on a net-metered account is recorded as a `CreditLedgerEntry`. Each entry carries the account's `service_account_id`, an `entry_type` drawn from `EXPORT_SURPLUS_CREDIT`, `CREDIT_APPLIED`, `BANK_DEPOSIT`, `BANK_DRAW`, `BANK_FORFEIT`, `TRUE_UP_PAYOUT`, `TRUE_UP_FORFEIT`, or `REVERSAL`, a signed `amount_cents` (credit-positive, debit-negative; zero for pure energy-bank entries), a signed `quantity_wh` (for energy-bank entries and net-surplus tracking; zero when not applicable), and the `posted_at` logical-clock instant of posting. Entries created by monthly netting reference their `meter_reading_id` and leave `annual_reconciliation_id` null; entries created by annual settlement reference their `annual_reconciliation_id` and leave `meter_reading_id` null.

Two account-level projections are derived from this ledger. The account's `credit_balance_cents` is the sum of `amount_cents` over every ledger entry the account has ever posted. The account's `banked_wh` is the sum of `quantity_wh` over entries whose `entry_type` is `BANK_DEPOSIT`, `BANK_DRAW`, or `BANK_FORFEIT`. Because the ledger is append-only, corrections follow an invariant: voiding or superseding a meter reading appends `REVERSAL` entries whose `amount_cents` and `quantity_wh` are the exact negation of that reading's original entries, so a posting followed by its reversal leaves both balances unchanged.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the version of a parent resource, because each can legitimately supersede existing state and must therefore not proceed on the basis of a stale read.

Issuing an upgrade cost estimate requires the request to carry `expected_application_version`, holding the `version` of the target application as the client last observed it. If the application's current `version` has advanced beyond that value, the create is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). Posting a meter reading requires the request to carry `expected_account_version`, holding the `version` of the target service account as the client last observed it; a mismatch with the account's current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Both guarded operations increment the parent's `version` by one on success. Endpoints not named here do not accept a version field.

### 2.10. Request Validation Pipeline

Every request is evaluated against an ordered pipeline of checks, and when several checks could reject the same request, the earliest check in this order determines the error returned. First, the presence of `X-User-ID` and `X-User-Role` and the recognition of the role name (`ERR_MISSING_CONTEXT_HEADER`). Second, the role's permission to invoke the endpoint (`ERR_FORBIDDEN_ROLE`). Third, for applicant-scoped mutating endpoints, ownership of the target resource (`ERR_FORBIDDEN_OWNERSHIP`). Fourth, the existence of every resource identifier in the path, validated left to right (`ERR_NOT_FOUND`). Fifth, request-schema soundness — required fields present, enum membership valid, quantities positive where required, an amend payload that is not empty, `period_end` strictly after `period_start` on readings, and a `deficiency_note` present whenever a completeness decision's `outcome` is `INCOMPLETE` (`ERR_INVALID_REQUEST`). Sixth, foreign keys in the request body — such as `service_account_id`, `program_id`, `transformer_id`, `feeder_id`, `customer_id`, `application_id`, and `supplemental_review_id` — resolving to existing resources (`ERR_INVALID_REFERENCE`). Seventh, the optimistic-concurrency checks of §2.9. Eighth, the primary resource being in a state that permits the requested transition (`ERR_INVALID_STATE`, or `ERR_ESTIMATE_NOT_ISSUED` for estimate accept and decline). Ninth, segregation of duties (`ERR_SEGREGATION_OF_DUTIES`). Tenth, temporal windows (`ERR_ESTIMATE_EXPIRED`, `ERR_INSPECTION_DATE_INVALID`, `ERR_TRUE_UP_WINDOW_NOT_OPEN`). Eleventh, structural business rules such as window overlaps, one-active-record uniqueness, document-set completeness, and eligibility limits. Twelfth, cross-entity gates such as program and account status, metering status, and prerequisite field work. Certain endpoints pin a finer ordering inside these categories; those are stated where the workflow is described.

## 3. Business Logic & Workflows

### 3.1. Programs, Tariffs, and Grid Topology

A `ProgramAdministrator` begins by standing up a net metering program, supplying its `name`, the program-wide `aggregate_cap_watts`, a `metering_variant` of `ENERGY_BANKING` or `MONETARY_CREDIT` (which selects how monthly netting treats surplus), a `true_up_mode` of `AVOIDED_COST_PAYOUT` or `BANK_ROLLOVER` (which selects how the annual true-up settles), a `true_up_month` from 1 to 12 anchoring the reconciliation calendar, a `screening_basis` of `COMMITTED` or `INCLUDE_QUEUED` governing technical screens, and optionally a `bank_cap_wh` — the watt-hour ceiling on the energy bank used only by `BANK_ROLLOVER` true-ups, where null means unlimited. A new program starts in `program_status` `OPEN` with its capacity ledger initialized to zero reservations, zero interconnected watts, and an empty queue. The program list view may be filtered by `program_status`.

Programs move through a simple administrative lifecycle. Suspending an `OPEN` or `CAP_REACHED` program moves it to `SUSPENDED`, and while suspended the program rejects new application submissions. Resuming returns it to `OPEN` when capacity is available and to `CAP_REACHED` otherwise, per the posture recompute of §2.7. Closing is terminal: a program may move from `OPEN`, `CAP_REACHED`, or `SUSPENDED` to `CLOSED` only when no application of the program remains in a non-terminal status; otherwise the close is rejected with `ERR_PROGRAM_HAS_INFLIGHT_WORK`.

Tariff schedules price the energy flows. Each schedule belongs to a program via `program_id`, carries a human-readable `schedule_code`, and defines a half-open effectiveness window — inclusive of `effective_from`, exclusive of `effective_to`, with a null `effective_to` meaning open-ended. Two schedules of the same program may touch at a boundary but may not overlap; an overlapping creation is rejected with `ERR_TARIFF_WINDOW_OVERLAP`. Every schedule carries three strictly positive integer rates: `import_rate_millicents_per_kwh` for energy drawn from the grid, `export_rate_millicents_per_kwh` for surplus credited under the `MONETARY_CREDIT` variant, and `net_surplus_rate_millicents_per_kwh` for annual net-surplus compensation. The schedule list may be filtered by `program_id`.

The physical side of the model is a two-level topology. A feeder is registered with a unique `feeder_code`, its annual `peak_load_watts`, and any `pre_existing_der_watts` already on the feeder before this program (defaulting to zero). A service transformer is then registered on a feeder via `feeder_id`, with its own unique `transformer_code`, a strictly positive `nameplate_watts`, and its own `pre_existing_der_watts`. Both levels expose a computed `aggregate_der_watts`: the pre-existing figure plus the reserved and interconnected watts of applications whose accounts sit on that equipment. Queued applications never contribute to `aggregate_der_watts`. Transformer lists may be filtered by `feeder_id`.

### 3.2. Customers and Service Accounts

The back office registers each customer with a `full_name` and `email`. A service account is then opened for a customer on a serving transformer, capturing `customer_id`, `transformer_id` (which also determines the feeder), a unique `account_number`, a `service_class` of `RESIDENTIAL`, `COMMERCIAL`, or `INDUSTRIAL`, and the `prior_annual_usage_wh` — the prior twelve months of consumption in watt-hours, zero or greater, which anchors eligibility. New accounts start with `account_status` `ACTIVE`, `metering_status` `STANDARD`, a null `meter_serial`, and zero balances (`credit_balance_cents` and `banked_wh`). Account lists may be filtered by `customer_id`, `transformer_id`, or `account_status`.

Account standing is administered through two independent dimensions. On the `account_status` dimension, an administrator may suspend an `ACTIVE` account (moving it to `SUSPENDED`, which blocks both application submissions and meter readings), reactivate a `SUSPENDED` account back to `ACTIVE`, or close an account — from either `ACTIVE` or `SUSPENDED` — provided no non-terminal application references it, failing which the close is rejected with `ERR_ACCOUNT_HAS_INFLIGHT_APPLICATIONS`. On the `metering_status` dimension, the account moves from `STANDARD` to `NET_METERING` automatically the moment permission to operate is granted on one of its applications, and meter readings are accepted from that point on. The dimensions evolve in parallel: an account may legitimately be `SUSPENDED` while `NET_METERING`.

### 3.3. Application Intake, Documents, and the Completeness Decision

An applicant initiates the process by creating an application against an account they own, choosing a `technology` of `SOLAR_PV`, `WIND`, or `FUEL_CELL` and declaring the `system_size_watts_ac` and `estimated_annual_production_wh`, both strictly positive. The application is born in `application_status` `DRAFT` with `submission_round` at zero, `capacity_reserved_watts` at zero, no `submitted_at`, `reservation_expires_at`, or `pto_granted_at`, and both `denial_reason` and `withdrawal_reason` null. Application lists may be filtered by `service_account_id`, `program_id`, or `application_status`.

Submission moves a `DRAFT` application to `PENDING_COMPLETENESS`; it requires the program to be `OPEN` or `CAP_REACHED` (otherwise `ERR_PROGRAM_NOT_ACCEPTING`), the account to be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`), and no other non-terminal application to exist for the same account (otherwise `ERR_DUPLICATE_ACTIVE_APPLICATION`). A successful first submission stamps `submitted_at` with the current clock time and sets `submission_round` to one. An application sent back as `INCOMPLETE` may be resubmitted under the same program-and-account conditions; resubmission stamps `submitted_at` again and increments `submission_round` by one.

Supporting paperwork is uploaded as documents, each tied to the application via `application_id` with a `doc_type` of `SITE_PLAN`, `SINGLE_LINE_DIAGRAM`, or `INSURANCE_CERTIFICATE` and a free-text `title`. Uploads are accepted while the application is `DRAFT`, `PENDING_COMPLETENESS`, `INCOMPLETE`, or `SUPPLEMENTAL_REVIEW`, and each document starts with `review_status` `UPLOADED`. A coordinator then reviews each uploaded document to `ACCEPTED` or `REJECTED`, storing a `review_note` with the decision; document lists may be filtered by `application_id` or `review_status`.

The completeness decision itself belongs to the `InterconnectionCoordinator`, who supplies an `outcome` of `COMPLETE` or `INCOMPLETE`. Marking an application `INCOMPLETE` requires at least one of its documents to be in `REJECTED` status — otherwise the decision is rejected with `ERR_NO_REJECTED_DOCUMENTS` — and the payload must carry a `deficiency_note` explaining the gaps, with a missing note rejected as `ERR_INVALID_REQUEST`; the application returns to `INCOMPLETE` awaiting resubmission. Marking `COMPLETE` first requires the full required document set — one accepted document of each of the three types — to be entirely `ACCEPTED`; deciding `COMPLETE` against an incomplete set is rejected with `ERR_INCOMPLETE_DOCUMENTS`.

A `COMPLETE` decision then runs the eligibility screen inline. The size check comes first: if `system_size_watts_ac` exceeds the cap for the account's `service_class` — 25,000 watts (25 kW) for `RESIDENTIAL`, 1,000,000 watts (1 MW) for `COMMERCIAL`, 5,000,000 watts (5 MW) for `INDUSTRIAL` — the application is denied with `denial_reason` `SIZE_EXCEEDS_CLASS_CAP`. Otherwise the production check runs: the production cap is the account's `prior_annual_usage_wh` multiplied by 110 percent with the product floored to whole watt-hours, and if `estimated_annual_production_wh` exceeds that cap the application is denied with `denial_reason` `PRODUCTION_EXCEEDS_LOAD`. Estimated production exactly equal to the cap passes, and an account with zero prior usage fails any positive production estimate. A denial lands the application in terminal `DENIED` status.

An eligible application finally claims capacity. When the program's `available_capacity_watts` is at least the requested size, the application moves to `CAPACITY_RESERVED`: `capacity_reserved_watts` is set to the system size, `reservation_expires_at` is set 180 days out, the program's `reserved_watts` grows by the size, the serving transformer and feeder `aggregate_der_watts` grow likewise, and the program posture is recomputed. When capacity falls short, the application instead joins the queue in `WAITING_FOR_CAPACITY`: it receives the next `queue_position` — one more than the highest position currently held in the program, or 1 when the queue is empty — and the program's `queued_count` increases by one. Positions are one-based, and `queue_position` is null whenever the application is not queued.

### 3.4. Technical Screening and Supplemental Review

With capacity reserved, a `DistributionEngineer` runs the technical screens by commissioning a screening report for the application. Each report carries a `screening_round` equal to one plus the number of prior reports for that application, is created with `report_status` `CURRENT`, and supersedes any previously `CURRENT` report, which moves to `SUPERSEDED`. The report copies the program's `screening_basis` into its own `aggregate_basis` at compute time, so a report forever reflects the basis under which it was run. Reports may be listed and filtered by `application_id`.

Three screens are computed, each recorded on the report. For the transformer and feeder screens, the server first builds a basis aggregate at each node: the node's `pre_existing_der_watts`, plus the sizes of other reservation-holding applications — those in `CAPACITY_RESERVED`, `SUPPLEMENTAL_REVIEW`, `SCREEN_PASSED`, `AWAITING_COST_ESTIMATE`, `CUSTOMER_DECISION_PENDING`, or `UPGRADE_IN_PROGRESS` — whose accounts sit on the node, plus the sizes of interconnected applications (`PTO_GRANTED` or `OPERATING`) on the node. When the program's basis is `INCLUDE_QUEUED`, the sizes of queued (`WAITING_FOR_CAPACITY`) applications on the node are added as well; under `COMMITTED` they are excluded, so identical grid data can flip a screen between the two bases. The application being screened is deliberately excluded from its own basis aggregate — its size is added exactly once afterward, since as a reservation holder it would otherwise be double-counted.

The transformer screen compares `transformer_aggregate_after_watts` — the transformer's basis aggregate plus the screened size — against `transformer_limit_watts`, which is half of `nameplate_watts` floored to whole watts; the screen passes when the after-figure is less than or equal to the limit, and `transformer_screen_passed` records the verdict. The feeder screen compares `feeder_aggregate_after_watts` against `feeder_limit_watts`, which is fifteen percent of `peak_load_watts` floored to whole watts; this screen is strict — the after-figure must be strictly less than the limit, and equality fails — with the verdict in `feeder_screen_passed`. The fast-track screen simply checks whether the system size is at most 2,000,000 watts (2 MW), recording the verdict in `size_within_fast_track`. The report's `outcome` is `PASSED` when all three screens pass and `FAILED` otherwise, with `failing_screens` holding the ordered subset of `TRANSFORMER_CAPACITY`, `FEEDER_PENETRATION`, and `FAST_TRACK_SIZE` that failed. A passing report moves the application from `CAPACITY_RESERVED` to `SCREEN_PASSED`; any failure routes it to `SUPPLEMENTAL_REVIEW`.

In supplemental review, the engineer opens a study — at most one `OPEN` review per application, with a second attempt rejected as `ERR_SUPPLEMENTAL_REVIEW_OPEN` — choosing a `review_type` of `FACILITIES_STUDY` or `SYSTEM_IMPACT_STUDY` and optionally recording `findings`; the new review starts with `review_status` `OPEN` and a null `outcome`. Completing the review stores an `outcome` and moves the review to `COMPLETED`: `CLEARED` returns the application to `SCREEN_PASSED`; `UPGRADES_REQUIRED` moves it to `AWAITING_COST_ESTIMATE` to await pricing; `DENIED` terminates the application with `denial_reason` `TECHNICALLY_INFEASIBLE`, releases its reservation — subtracting the reserved watts from the program, transformer, and feeder aggregates, zeroing `capacity_reserved_watts`, and clearing `reservation_expires_at` — and triggers the queue promotion scan and posture recompute. Reviews left `OPEN` when the application is amended or withdrawn are closed automatically (`CLOSED`). Reviews may be listed and filtered by `application_id`.

### 3.5. Upgrade Cost Estimates and the Customer Decision

When upgrades are required, the `DistributionEngineer` prices them by issuing an upgrade cost estimate naming the `application_id` and the `supplemental_review_id` that required the work. The estimate's `items` are an array of line entries, each pairing a free-text `description` with a non-negative integer `amount_cents`, and a `contingency_pct` between 0 and 100 expresses the contingency allowance. The estimate's `total_cents` is the sum of the line amounts, scaled by one plus the contingency percentage — that is, the subtotal multiplied by (100 + `contingency_pct`) and divided by 100 — with a single round-half-up to whole cents applied only at the end. Issuance stamps `valid_until` thirty days out, marks the estimate `ISSUED`, supersedes any currently `ISSUED` estimate for the same application (moving it to `SUPERSEDED`), moves the application from `AWAITING_COST_ESTIMATE` to `CUSTOMER_DECISION_PENDING`, and increments the application's `version` by one. Because issuance supersedes, it is guarded by the `expected_application_version` concurrency check of §2.9, and a further issuance while the customer is deciding keeps the application in `CUSTOMER_DECISION_PENDING` with the same supersession cascade. Estimates may be listed and filtered by `application_id`, `supplemental_review_id`, or `estimate_status`.

The customer decision rests with the applicant. Accepting is allowed only while the estimate is still `ISSUED` — attempting to accept or decline an estimate in any other status is rejected with `ERR_ESTIMATE_NOT_ISSUED` — and only on or before `valid_until`; an accept attempted after that instant, while the estimate still shows `ISSUED` because the sweep has not run, is rejected with `ERR_ESTIMATE_EXPIRED`. Acceptance records `decided_at`, moves the estimate to `ACCEPTED`, and moves the application to `UPGRADE_IN_PROGRESS`. Declining records `decided_at`, moves the estimate to `DECLINED`, and withdraws the application with `withdrawal_reason` `CUSTOMER_DECLINED`, triggering the full release cascade of §3.6. Should the decision window lapse, the program sweep expires the estimate (`EXPIRED`) and withdraws the application with `withdrawal_reason` `ESTIMATE_EXPIRED`. Once upgrade construction finishes, the engineer marks the work complete: the `ACCEPTED` estimate moves to `WORK_COMPLETE` and the application returns to `SCREEN_PASSED`, ready for final inspection and energization. An application withdrawn for any reason also cancels its still-`ISSUED` estimates (`CANCELLED`).

### 3.6. Amending or Withdrawing an Application Mid-Flight

Designs evolve, and an applicant may amend an application while it is in `DRAFT`, `CAPACITY_RESERVED`, or `SUPPLEMENTAL_REVIEW`, revising any of `system_size_watts_ac`, `estimated_annual_production_wh`, or `technology`; a payload touching none of these is rejected as `ERR_INVALID_REQUEST`. Amending re-runs the eligibility screen of §3.3 against the amended values, and failures surface as request errors rather than denials: an amended size above the class cap is rejected with `ERR_SIZE_EXCEEDS_CLASS_CAP`, and an amended production estimate above the 110-percent-of-usage cap is rejected with `ERR_PRODUCTION_EXCEEDS_LOAD` — the size check is always evaluated first, so an amendment violating both reports the size violation. A successful amendment supersedes the application's `CURRENT` screening reports and closes its `OPEN` supplemental reviews, since the engineering record no longer describes the design on file. Amendment leaves a `DRAFT` application in `DRAFT`; an amendment made from `SUPPLEMENTAL_REVIEW` returns the application to `CAPACITY_RESERVED` once the capacity rule below is satisfied; and an amendment made from `CAPACITY_RESERVED` keeps it there, unless the size increase triggers the release-and-requeue path, in which case the application lands in `WAITING_FOR_CAPACITY`.

When the application holds a reservation, amending also rebalances capacity. An increase in size requires the program's `available_capacity_watts` to cover at least the delta; when it does not, the reservation is released and the application re-enters the capacity queue, taking the next `queue_position` per the assignment rule. A decrease frees the difference back to the program and immediately triggers the queue promotion scan. In the promotion scan — which also runs after any capacity release, after the sweep, and after a reservation-losing withdrawal or denial — the program's queued applications are considered in ascending `queue_position`; each whose size fits within the current `available_capacity_watts` is promoted to `CAPACITY_RESERVED` with `capacity_reserved_watts` set to its size, a fresh 180-day `reservation_expires_at`, and its `queue_position` cleared to null, its watts folded into `reserved_watts` and the equipment aggregates, `queued_count` decremented, and the available figure recomputed before the next candidate is considered. Applications that do not fit are skipped and remain queued, and the scan continues past them; evaluation order is pinned ascending, and the available capacity is recomputed after every promotion, so a different order could promote a different subset. Whenever an application leaves the queue — by promotion, withdrawal, or expiry — every remaining queued application with a higher `queue_position` is renumbered down by one, closing the gap.

Withdrawal is the applicant's exit. Any application in a non-terminal status other than `PTO_GRANTED` or `OPERATING` may be withdrawn — attempting withdrawal from those two states is rejected with `ERR_INVALID_STATE` — and lands in `WITHDRAWN` with `withdrawal_reason` `APPLICANT_WITHDRAWN`. The release cascade then unwinds everything the application held: a queued application releases its `queue_position`, higher positions renumber down, and `queued_count` decreases; a reservation-holding application returns its watts to the program and equipment aggregates, zeroes `capacity_reserved_watts`, clears `reservation_expires_at`, and triggers the promotion scan and posture recompute. Dependent records are settled in kind: `OPEN` supplemental reviews move to `CLOSED`, still-`ISSUED` cost estimates move to `CANCELLED`, `SCHEDULED` inspections move to `CANCELLED`, and `SCHEDULED` or `FAILED` meter exchanges move to `CANCELLED`. The sweep of §2.4 reaches the same terminal state via `RESERVATION_EXPIRED` or `ESTIMATE_EXPIRED` when time runs out.

### 3.7. Field Work: Meter Exchange and Inspection

Once an application reaches `SCREEN_PASSED`, the meter shop schedules the bidirectional meter exchange. A `MeterTechnician` books an appointment by supplying the `application_id`, the `crew_id` of the assigned crew, and a `window_start` and `window_end`; an end that is not strictly after the start is rejected with `ERR_EXCHANGE_WINDOW_INVALID`. The new exchange starts in `exchange_status` `SCHEDULED`. Only one active exchange may exist per application — a second `SCHEDULED` exchange is rejected with `ERR_EXCHANGE_ALREADY_ACTIVE` — and crews are protected by a half-hour buffer: the half-open interval from thirty minutes before `window_start` to thirty minutes after `window_end` may not intersect the corresponding buffered window of any other `SCHEDULED` exchange for the same `crew_id`, failing which the booking is rejected with `ERR_EXCHANGE_WINDOW_OVERLAP`. Exchange lists may be filtered by `application_id`, `crew_id`, or `exchange_status`.

The visit resolves in one of three ways. Completion moves the exchange to `COMPLETED`, records the `installed_meter_serial` and the acting technician's identity in `technician_user_id`, and copies the serial onto the account's `meter_serial`. A failed visit moves the exchange to `FAILED` with a `fail_reason`, and the technician may reschedule a failed exchange with a fresh `window_start` and `window_end` — revalidated against the window-ordering and crew-buffer rules — returning it to `SCHEDULED` and clearing the `fail_reason`. Either a `SCHEDULED` or a `FAILED` exchange may be cancelled outright (`CANCELLED`), and withdrawal of the parent application cancels them automatically.

With a completed exchange in place, the applicant requests an inspection, proposing a `scheduled_date` that must not be earlier than the current clock time (otherwise `ERR_INSPECTION_DATE_INVALID`); the request requires the application to be `SCREEN_PASSED`, a completed meter exchange to exist for it (otherwise `ERR_METER_EXCHANGE_NOT_COMPLETED`), and no other `SCHEDULED` inspection to be outstanding for the same application (otherwise `ERR_INSPECTION_EXISTS`). The request creates the inspection in `inspection_status` `SCHEDULED`, with `outcome`, `occurred_at`, `defects`, and `inspector_user_id` all unset until a result is recorded. Inspection lists may be filtered by `application_id` or `inspection_status`. An `Inspector` later records the result: the `occurred_at` instant must fall on or after `scheduled_date` and on or before the current clock time — outside that window the record is rejected with `ERR_INSPECTION_DATE_INVALID` — and a `defects` narrative is required exactly when the recorded `outcome` is `FAILED`, with a missing narrative rejected as `ERR_DEFECTS_REQUIRED`. Segregation of duties is enforced at this point: the inspector recording the result must not be the same individual as the `technician_user_id` who completed that application's meter exchange, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES`. A recorded result moves the inspection to `RESULT_RECORDED` and stores `inspector_user_id`; the applicant may instead cancel a `SCHEDULED` inspection (`CANCELLED`), as does withdrawal of the application.

### 3.8. Permission to Operate and Energization

The `InterconnectionCoordinator` grants permission to operate once the evidence chain is complete, moving the application from `SCREEN_PASSED` to `PTO_GRANTED`. Four gates guard the grant, and the order between two of them is pinned: the account must be `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); a completed meter exchange must exist for the application (`ERR_METER_EXCHANGE_NOT_COMPLETED`, checked before the inspection gate); the latest inspection — the one with the greatest `created_at` — must be `RESULT_RECORDED` with `outcome` `PASSED` (`ERR_INSPECTION_NOT_PASSED`); and a tariff schedule of the program must be effective at the current clock time (`ERR_NO_EFFECTIVE_TARIFF`).

The grant's side effects convert the reservation into live capacity: `pto_granted_at` is stamped, the program's `reserved_watts` falls by the reserved amount while `interconnected_watts` rises by the same amount — leaving `available_capacity_watts` unchanged — `capacity_reserved_watts` returns to zero, `reservation_expires_at` is cleared, and the account's `metering_status` moves from `STANDARD` to `NET_METERING`, unlocking billing. From there, the application sits in `PTO_GRANTED` until the first meter reading posts for the account, at which point the system moves it to `OPERATING`, its terminal operating state. Withdrawal and any further lifecycle action are forbidden from both `PTO_GRANTED` and `OPERATING`.

### 3.9. Metering, Monthly Netting, and the Annual True-Up

Once an account is net-metered, a `MeterTechnician` posts period readings carrying `service_account_id`, a half-open billing window from `period_start` (inclusive) to `period_end` (exclusive, and strictly after the start), and the period's `import_wh` and `export_wh`, each zero or greater. Two cross-entity gates run in a pinned order: the account's `metering_status` must be `NET_METERING` first (`ERR_ACCOUNT_NOT_NET_METERING`), and only then is `account_status` checked for `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`). A tariff schedule of the account's program must be effective at `period_start` (`ERR_NO_EFFECTIVE_TARIFF`), and the reading pins that tariff into its `tariff_id` for netting. Period uniqueness is exact-match semantics: a new reading whose `period_start` and `period_end` exactly equal an existing `POSTED` reading's supersedes it — the old reading moves to `SUPERSEDED` and `REVERSAL` entries negate its ledger postings — while a period that only partially overlaps a `POSTED` reading is rejected with `ERR_READING_PERIOD_OVERLAP`. Because supersession rewrites history, the create carries the `expected_account_version` check of §2.9 and increments the account's `version` by one on success. Each new reading is created in `reading_status` `POSTED`, and the first reading to post also flips the account's application from `PTO_GRANTED` to `OPERATING`. Reading lists may be filtered by `service_account_id`, `reading_status`, or `tariff_id`, and a technician may void a `POSTED` reading by supplying a `reason`, moving it to `VOIDED` with the same compensating `REVERSAL` entries.

Monthly netting converts the reading into money. The offset between the two flows is the smaller of `import_wh` and `export_wh`; the surplus is the export minus that offset, and the billable import is the import minus that offset. Under the `MONETARY_CREDIT` variant, the raw bill is the billable import converted to cents at the tariff's import rate with a round-half-up; the surplus is converted to cents at the export rate with its own round-half-up and, when positive, posted as an `EXPORT_SURPLUS_CREDIT` ledger entry carrying the credit in `amount_cents` and the surplus watt-hours in `quantity_wh`. The account's credit bank then offsets the bill: the draw is the smaller of the current `credit_balance_cents` and the raw bill and, when positive, posts a `CREDIT_APPLIED` entry debiting that amount; the reading's `bill_cents` is the raw bill minus the draw, `credit_applied_cents` records the draw, and both `bank_drawn_wh` and `bank_deposited_wh` are zero.

Under the `ENERGY_BANKING` variant, energy offsets energy. The period's net is the import minus the export. When the net is positive, the draw is the smaller of the account's `banked_wh` and the net; a positive draw posts a `BANK_DRAW` entry with zero cents and the drawn watt-hours negative in `quantity_wh`, and the bill is the remaining unbanked energy converted to cents at the import rate, rounded half-up, with `bank_drawn_wh` recording the draw. When the net is zero or negative, the surplus — the negation of the net — is deposited: a positive deposit posts a `BANK_DEPOSIT` entry with zero cents and the deposited watt-hours positive in `quantity_wh`, the bill is zero, and `bank_deposited_wh` records the deposit. Either way `credit_applied_cents` is zero. Identical readings therefore produce different bills and balances under the two variants, which is why the program's `metering_variant` is fixed at configuration time.

Once a year, the program office computes the annual true-up for an account by naming its `service_account_id` and a `reconciliation_year`; the reconciliation is created in `reconciliation_status` `COMPUTED`. The reconciliation window runs from the first day of the program's `true_up_month` in that year, inclusive, to the first day of the same month in the following year, exclusive, and is recorded as `window_start` and `window_end`. Computation is allowed only during the run window — from `window_end` up to but not including sixty days after it — with attempts outside rejected as `ERR_TRUE_UP_WINDOW_NOT_OPEN`, and at most one reconciliation in `COMPUTED` or `SETTLED` status may exist per account and year, with duplicates rejected as `ERR_DUPLICATE_TRUE_UP`. The computed `surplus_wh` sums, over the account's `POSTED` readings whose `period_start` falls inside the window (superseded and voided readings excluded), each period's positive part of export minus import — periods that net to zero or negative contribute nothing. The tariff effective at computation time is pinned to `tariff_id`, and `nsc_cents` is the `surplus_wh` converted to cents at that tariff's `net_surplus_rate_millicents_per_kwh`, rounded half-up.

Settlement depends on the program's `true_up_mode`, and the rounding order is pinned: the credit bank being settled is the sum of per-reading cent-rounded credits from §2.8, and the annual figures are derived from that posted balance, never from a whole-year recompute of raw watt-hours. Under `AVOIDED_COST_PAYOUT`, the reconciliation captures `credit_balance_at_compute_cents`; `payout_cents` is the smaller of that balance and `nsc_cents`, and `forfeited_cents` is the remainder of the balance above the payout. Finalizing a `COMPUTED` reconciliation posts a `TRUE_UP_PAYOUT` entry debiting the payout when positive and a `TRUE_UP_FORFEIT` entry debiting the forfeiture when positive, zeroing the credit bank, and moves the reconciliation to `SETTLED`. Under `BANK_ROLLOVER` there is no payout: `payout_cents` and `forfeited_cents` are both zero, and `forfeited_wh` is the amount by which the account's `banked_wh` exceeds the program's `bank_cap_wh` — zero when the cap is null or not exceeded. Finalizing posts a `BANK_FORFEIT` entry with the forfeited watt-hours negative in `quantity_wh` when positive, so the bank rolls forward at no more than the cap. A reconciliation computed in error may instead be voided — moving it to `VOIDED` with no ledger effect, freeing the account-year slot for recomputation. Reconciliation lists may be filtered by `service_account_id`, `reconciliation_status`, or `tariff_id`, and the append-only ledger of §2.8 may be browsed by `service_account_id`, `meter_reading_id`, `annual_reconciliation_id`, or `entry_type`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code; operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a summary only — request payloads, responses, and side effects are defined by the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | ProgramAdministrator |
| GET | `/_clock` | Read the logical clock | Any |
| POST | `/programs` | Create a net metering program | ProgramAdministrator |
| GET | `/programs` | List programs | Any |
| GET | `/programs/{program_id}` | Get a program | Any |
| POST | `/programs/{program_id}/suspend` | Suspend program intake | ProgramAdministrator |
| POST | `/programs/{program_id}/resume` | Resume program intake | ProgramAdministrator |
| POST | `/programs/{program_id}/close` | Close a program (terminal) | ProgramAdministrator |
| POST | `/programs/{program_id}/sweep` | Run the expiry sweep for a program | ProgramAdministrator |
| POST | `/tariff-schedules` | Create a tariff window for a program | ProgramAdministrator |
| GET | `/tariff-schedules` | List tariff schedules | Any |
| GET | `/tariff-schedules/{tariff_schedule_id}` | Get a tariff schedule | Any |
| POST | `/feeders` | Register a feeder | ProgramAdministrator |
| GET | `/feeders` | List feeders | Any |
| GET | `/feeders/{feeder_id}` | Get a feeder | Any |
| POST | `/service-transformers` | Register a service transformer on a feeder | ProgramAdministrator |
| GET | `/service-transformers` | List service transformers | Any |
| GET | `/service-transformers/{service_transformer_id}` | Get a service transformer | Any |
| POST | `/customers` | Register a customer | ProgramAdministrator |
| GET | `/customers` | List customers | Any |
| GET | `/customers/{customer_id}` | Get a customer | Any |
| POST | `/service-accounts` | Open a service account on a transformer | ProgramAdministrator |
| GET | `/service-accounts` | List service accounts | Any |
| GET | `/service-accounts/{service_account_id}` | Get a service account | Any |
| POST | `/service-accounts/{service_account_id}/suspend` | Suspend an account | ProgramAdministrator |
| POST | `/service-accounts/{service_account_id}/reactivate` | Reactivate an account | ProgramAdministrator |
| POST | `/service-accounts/{service_account_id}/close` | Close an account (terminal) | ProgramAdministrator |
| POST | `/applications` | Create an application in `DRAFT` | Applicant |
| GET | `/applications` | List applications | Any |
| GET | `/applications/{application_id}` | Get an application | Any |
| POST | `/applications/{application_id}/submit` | Submit or resubmit for completeness screening | Applicant |
| POST | `/applications/{application_id}/amend` | Amend the design mid-flight | Applicant |
| POST | `/applications/{application_id}/withdraw` | Withdraw a non-terminal application | Applicant |
| POST | `/applications/{application_id}/completeness-decision` | Record the completeness decision | InterconnectionCoordinator |
| POST | `/applications/{application_id}/grant-pto` | Grant permission to operate | InterconnectionCoordinator |
| POST | `/documents` | Upload an application document | Applicant |
| GET | `/documents` | List documents | Any |
| GET | `/documents/{document_id}` | Get a document | Any |
| POST | `/documents/{document_id}/review` | Accept or reject an uploaded document | InterconnectionCoordinator |
| POST | `/screening-reports` | Run the technical screens for an application | DistributionEngineer |
| GET | `/screening-reports` | List screening reports | Any |
| GET | `/screening-reports/{screening_report_id}` | Get a screening report | Any |
| POST | `/supplemental-reviews` | Open a supplemental review | DistributionEngineer |
| GET | `/supplemental-reviews` | List supplemental reviews | Any |
| GET | `/supplemental-reviews/{supplemental_review_id}` | Get a supplemental review | Any |
| POST | `/supplemental-reviews/{supplemental_review_id}/complete` | Complete a supplemental review | DistributionEngineer |
| POST | `/cost-estimates` | Issue an upgrade cost estimate | DistributionEngineer |
| GET | `/cost-estimates` | List cost estimates | Any |
| GET | `/cost-estimates/{cost_estimate_id}` | Get a cost estimate | Any |
| POST | `/cost-estimates/{cost_estimate_id}/accept` | Accept an issued estimate | Applicant |
| POST | `/cost-estimates/{cost_estimate_id}/decline` | Decline an issued estimate | Applicant |
| POST | `/cost-estimates/{cost_estimate_id}/mark-work-complete` | Mark upgrade construction complete | DistributionEngineer |
| POST | `/meter-exchanges` | Schedule a bidirectional meter exchange | MeterTechnician |
| GET | `/meter-exchanges` | List meter exchanges | Any |
| GET | `/meter-exchanges/{meter_exchange_id}` | Get a meter exchange | Any |
| POST | `/meter-exchanges/{meter_exchange_id}/complete` | Record exchange completion | MeterTechnician |
| POST | `/meter-exchanges/{meter_exchange_id}/fail` | Record a failed exchange visit | MeterTechnician |
| POST | `/meter-exchanges/{meter_exchange_id}/reschedule` | Reschedule a failed exchange | MeterTechnician |
| POST | `/meter-exchanges/{meter_exchange_id}/cancel` | Cancel a scheduled or failed exchange | MeterTechnician |
| POST | `/inspections` | Request an inspection | Applicant |
| GET | `/inspections` | List inspections | Any |
| GET | `/inspections/{inspection_id}` | Get an inspection | Any |
| POST | `/inspections/{inspection_id}/record-result` | Record an inspection outcome | Inspector |
| POST | `/inspections/{inspection_id}/cancel` | Cancel a scheduled inspection | Applicant |
| POST | `/meter-readings` | Post a period meter reading | MeterTechnician |
| GET | `/meter-readings` | List meter readings | Any |
| GET | `/meter-readings/{meter_reading_id}` | Get a meter reading | Any |
| POST | `/meter-readings/{meter_reading_id}/void` | Void a posted reading | MeterTechnician |
| GET | `/ledger-entries` | List credit ledger entries | Any |
| GET | `/ledger-entries/{ledger_entry_id}` | Get a ledger entry | Any |
| POST | `/annual-reconciliations` | Compute the annual true-up for an account | ProgramAdministrator |
| GET | `/annual-reconciliations` | List annual reconciliations | Any |
| GET | `/annual-reconciliations/{annual_reconciliation_id}` | Get an annual reconciliation | Any |
| POST | `/annual-reconciliations/{annual_reconciliation_id}/finalize` | Settle a computed reconciliation | ProgramAdministrator |
| POST | `/annual-reconciliations/{annual_reconciliation_id}/void` | Void a computed reconciliation | ProgramAdministrator |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the workflows of §2 and §3; this catalogue lists only identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_REFERENCE` | 422 Unprocessable Entity |
| `ERR_STALE_APPLICATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ESTIMATE_NOT_ISSUED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_ESTIMATE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_INSPECTION_DATE_INVALID` | 422 Unprocessable Entity |
| `ERR_TRUE_UP_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_TARIFF_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_READING_PERIOD_OVERLAP` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_EXCHANGE_ALREADY_ACTIVE` | 422 Unprocessable Entity |
| `ERR_INSPECTION_EXISTS` | 422 Unprocessable Entity |
| `ERR_SUPPLEMENTAL_REVIEW_OPEN` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_APPLICATION` | 422 Unprocessable Entity |
| `ERR_INCOMPLETE_DOCUMENTS` | 422 Unprocessable Entity |
| `ERR_NO_REJECTED_DOCUMENTS` | 422 Unprocessable Entity |
| `ERR_DEFECTS_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SIZE_EXCEEDS_CLASS_CAP` | 422 Unprocessable Entity |
| `ERR_PRODUCTION_EXCEEDS_LOAD` | 422 Unprocessable Entity |
| `ERR_PROGRAM_NOT_ACCEPTING` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_NOT_NET_METERING` | 422 Unprocessable Entity |
| `ERR_METER_EXCHANGE_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_INSPECTION_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_NO_EFFECTIVE_TARIFF` | 422 Unprocessable Entity |
| `ERR_PROGRAM_HAS_INFLIGHT_WORK` | 422 Unprocessable Entity |
| `ERR_ACCOUNT_HAS_INFLIGHT_APPLICATIONS` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_TRUE_UP` | 422 Unprocessable Entity |
