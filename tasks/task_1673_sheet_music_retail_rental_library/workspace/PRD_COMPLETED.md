# Sheet Music Rental Library API — Product Requirements Document

## 1. Introduction

A music publisher's rental library sits at an awkward crossroads: it is part warehouse of finite physical performance materials, part licensing gatekeeper, and part retail shop. Schools, institutions, and individuals borrow complete sets of scores and parts for concerts whose dates overlap in unpredictable ways; publishers impose per-catalog rules about whether works may circulate digitally, whether perusal copies are offered, and whether a title is even in print; and every returned set must be inspected, with damage billed under strict segregation of duties so that the clerk grading a battered part is never the manager invoicing for it.

This document specifies the API for that library, mounted under `/library`. It governs catalog and publisher governance; reservation and allocation of physical rental copies against overlapping loan windows; dispatch, receipt confirmation, renewal, and return of orders; condition assessment and damage invoicing with a full dispute loop; institutional purchase orders and credit enforcement against a dual-ledger measure of account exposure; perusal and approval copies with buffered hold intervals and conversion into rentals or purchases; retail sales; out-of-print sourcing estimates; and a performance-rights advisory workflow that gates the dispatch of restricted works. A controllable logical clock and a daily batch sweep drive all time-based transitions so that overdue loans, stale approvals, and expiring purchase orders advance deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` names their operational capacity. Six roles exist, spelled exactly as follows: `LibraryAdmin` (catalog, sets, accounts, clock and sweep, publisher governance), `LibraryClerk` (front desk: reservations, dispatch, renewals, perusals, sales, lost copies), `ReturnsClerk` (returns desk: check-in, condition assessment, perusal returns), `BillingManager` (billing and credit: purchase orders, damage invoices, payments, standing, credit adjustments), `RightsAdvisor` (performance-rights specialist), and `Customer` (external account holder — a school or institution contact, or an individual). A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); this header check applies to every endpoint except the two system capabilities — setting the logical clock and running the daily sweep — which are restricted to `LibraryAdmin` in any case. A request whose role is not permitted for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `LibraryAdmin`, `LibraryClerk`, `ReturnsClerk`, `BillingManager`, or `RightsAdvisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `assessor_user_id` on a condition report, as `issuer_user_id` on a damage invoice, or as `decided_by_user_id` on a rights advisory case — but does not compare it to any entity's `id` except where a rule explicitly says so, notably the segregation-of-duties check in §3.6. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting CustomerAccount. Ownership checks compare a resource's `account_id` to `X-User-ID` and reject a mismatch with `ERR_FORBIDDEN_ACCOUNT` (HTTP 403), and they apply only where this document says so explicitly: a `Customer` reading an account record (§3.3), confirming receipt of a rental order (§3.5), disputing a rental order (§3.6), and withdrawing a rights advisory case (§3.9). Other reads and list endpoints are not ownership-scoped.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.6 rather than wall-clock time.
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

Requests to unknown paths, requests using an unsupported method, and unexpected server failures are answered in this same envelope with `error_id` `ERR_INVALID_REQUEST` and HTTP status 404, 405, or 500 respectively.

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100, and a supplied value outside that range is clamped to the nearest bound rather than rejected. `offset` specifies how many items to skip and defaults to 0, with negative values clamped to 0. A non-numeric `limit` or `offset` fails with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, breaking ties by creation order. The `meta` object of list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource type in the system — Publisher, Work, RentalSet, CustomerAccount, PurchaseOrder, RentalOrder, RentalLine, ConditionReport, DamageInvoice, PerusalRequest, SaleRecord, and RightsAdvisoryCase — carries four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, captured from the logical clock of §2.6 when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed from the same logical clock upon any change to the resource's properties.
- `version` (integer): a system-managed counter that starts at 1 on creation and increments by 1 with every modification to the resource.

Date-valued fields echo in field-specific formats: `checkout_date`, `due_date`, `valid_from`, and `valid_until` serialize as bare ISO 8601 dates; perusal timing fields (`ship_date`, `return_due_date`, `hold_start`, `hold_end`) and capability instants (`current_utc`, `quoted_expiry`) serialize as ISO 8601 UTC instants at second precision.

Recomputation of computed fields — exposure rollups on an account, fee re-estimates on an order, availability sync on a set, encumbrance on a purchase order — is itself a mutation of the owning resource and therefore refreshes `updated_at` and increments `version`, even when no client-visible field was directly edited.

### 2.5. Money, Precision, and Rounding Discipline

All monetary amounts in the system are represented as integer cents; there are no fractional-cent values anywhere in the API. Every annotated rounding step uses the round-half-up method. Where a calculation involves several rounding steps, the order of those steps is pinned and normative: rental fees round the per-copy-per-period tier rate first, then the discounted net, then the digital-format factor; damage charges round the per-copy replacement value before multiplying it by a degradation fraction; perusal-conversion pricing rounds the discounted per-unit price before multiplying by quantity; and late-fee arithmetic rounds the daily base exactly once before the tiered daily rates are derived from it. Alternative evaluation orders can diverge by several cents and are non-conformant.

### 2.6. The Logical Clock and the Daily Sweep

Time in this system is logical, not wall-clock. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. All state lives in memory per process: the store starts empty at every boot — no seed data of any kind — and nothing persists across restarts. A `LibraryAdmin` may advance the clock to a supplied `to_iso8601` instant; the supplied value may be a full ISO 8601 instant or a bare ISO date (read as midnight UTC), is adopted verbatim whether earlier or later than the current reading, and an unparseable value fails with `ERR_INVALID_REQUEST` (HTTP 400); the capability returns the resulting `current_utc`. Every date comparison in the system — due dates, purchase-order validity windows, perusal hold intervals, overdue detection — reads this clock.

A second admin-only capability runs the daily batch sweep. Each run moves every `ON_LOAN` rental whose due date has passed to `OVERDUE` (with the standing and purchase-order cascades described in §3.5); marks every `SHIPPED` perusal past its return due date as `OVERDUE_PERUSAL`; expires `APPROVED` perusals left unshipped for more than ten days; expires `APPROVED` purchase orders whose validity window has ended, provided no non-terminal rental orders reference them; and recomputes account standing with its purchase-order cascade. The sweep responds with tallies of its work: `swept_rentals`, `swept_perusals`, `swept_pos`, and `standing_flips`.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both take a mandatory version field. Renewing a rental order requires a non-optional `expected_rental_order_version` carrying the client's last observed `version` of that order; if the order's current `version` has advanced since that observation — because another writer renewed, checked in, disputed, or otherwise mutated the same order — the renewal is rejected with `ERR_STALE_VERSION` (HTTP 412). Applying a manual credit-limit adjustment to a customer account likewise requires a non-optional `expected_customer_account_version`; if a cascade such as an invoice issuance, a sweep-driven standing flip, or an exposure recompute has advanced the account's `version` since the client last read it, the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412). Each OCC field accepts an integer or a numeric string; a missing or non-numeric value fails shape validation with `ERR_INVALID_REQUEST` (HTTP 400) before any version comparison runs. Endpoints other than these two do not take a version field.

### 2.8. Resource Existence and Retrieval Order

Any identifier appearing in a request path is validated for existence before business rules run, left to right where several identifiers appear — account before order before line. The first identifier that does not correspond to an existing resource produces the resource-specific 404 error: `ERR_ACCOUNT_NOT_FOUND`, `ERR_PUBLISHER_NOT_FOUND`, `ERR_WORK_NOT_FOUND`, `ERR_RENTAL_SET_NOT_FOUND`, `ERR_PO_NOT_FOUND`, `ERR_RENTAL_ORDER_NOT_FOUND`, `ERR_RENTAL_LINE_NOT_FOUND`, `ERR_CONDITION_REPORT_NOT_FOUND`, `ERR_DAMAGE_INVOICE_NOT_FOUND`, `ERR_PERUSAL_REQUEST_NOT_FOUND`, `ERR_SALE_RECORD_NOT_FOUND`, or `ERR_RIGHTS_CASE_NOT_FOUND`. Identifiers carried in a request body (`publisher_id`, `account_id`, `work_id`, `rental_set_id`, `purchase_order_id`, `rental_line_id`, `condition_report_id`, `new_condition_report_id`, `perusal_request_id`) are validated against the same catalogs and produce the same resource-specific 404 errors; on creation endpoints this existence check runs after required-field presence and before the operation proceeds.

### 2.9. The Validation Pipeline

Every write request is evaluated against a fixed pipeline of validation tiers, and an earlier tier's failure masks every later tier — the surfaced error is always the earliest applicable one. The order is: (1) the user-context header check of §2.1; (2) role authorization; (3) path-resource existence per §2.8; (4) state-transition admissibility, where the target must sit in a from-state permitting the requested transition, else `ERR_INVALID_STATE` — a target value outside the resource's status vocabulary is no transition at all and falls to tier 19 instead; (5) segregation of duties on damage-invoice issuance and dispute resolution; (6) performance-rights clearance on dispatch; (7) license-format availability, evaluated at reservation for rentals and at approval for perusals (creation stores such requests unchecked); (8) rentability of the set, the work, and its publisher — at perusal approval this tier is the perusal-eligibility check of §3.7 (`ERR_PERUSAL_NOT_ALLOWED`) and runs before tier (7); (9) copy-window overlap at reservation; (10) renewal-window overlap at renewal; (11) perusal-hold separation at perusal approval; (12) purchase-order usability; (13) purchase-order amount headroom; (14) credit-limit headroom; (15) prepayment sufficiency at dispatch; (16) account-standing gates; (17) institution-only account-kind rules; (18) the renewal cap; (19) request-payload shape — the body must be a JSON object (an absent body reads as empty), required fields present, enum values valid, `due_date` later than `checkout_date`, quantities at least 1, dates well-formed, with unrecognized fields ignored — else `ERR_INVALID_REQUEST`; (20) the optimistic-concurrency version match of §2.7; (21) dispute-and-settle integrity; and (22) customer ownership scoping.

### 2.10. Loan Windows, Perusal Holds, and Quarantine Buffers

Rental copy allocation reasons over half-open date windows: a loan occupies its copies from `checkout_date` up to but not including `due_date`. Two windows that merely touch — one loan's `due_date` equal to another's `checkout_date`, or vice versa — do not overlap, so back-to-back bookings of the same copy are permitted. Dates are compared as ISO dates at day granularity. When the system walks candidate blocking lines as a batch, it processes them in `due_date` ascending order, breaking ties by `created_at` ascending.

Perusal holds follow stricter geometry: they are closed intervals with a mandatory quarantine buffer. A perusal hold runs from `hold_start` through `hold_end` inclusive, and a new hold on the same work must begin strictly after the previous hold's end — adjacency is forbidden, because a returned approval copy sits in a three-day quarantine before the next perusal of that work may ship.

## 3. Business Logic & Workflows

### 3.1. Publisher and Catalog Governance

A `LibraryAdmin` onboards each publisher with its legal `name` and a set of negotiated flags. `rental_discount_pct` — a value from 0 to 0.60 inclusive, defaulting to 0 — is a publisher-level discount applied against base rental rates at fee time. `allows_digital_perusal` (default false) declares whether the publisher's works may circulate as licensed, watermarked digital perusal copies. `print_only_rental` (default false) declares that rentals of this publisher's works must be fulfilled from physical sets; the digital fulfillment license is unavailable. `out_of_print` (default false) marks the catalog out of print: new stock orders are blocked and the sourcing-quote workflow becomes relevant. A publisher's `status` is `ACTIVE` or `SUSPENDED`; suspension blocks all new rental, perusal, and purchase activity on its works. Updating any of these flags, or toggling `status` between `ACTIVE` and `SUSPENDED` — the only legal transitions, each rejected with `ERR_INVALID_STATE` when attempted from the wrong from-state — increments the publisher's `version`.

Cataloging a work records its `publisher_id`, `title`, and `catalog_number`, the latter unique per publisher (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400). The `ensemble_tier` — `CHAMBER`, `BAND`, or `ORCHESTRA` — drives the base rental rate tier used by the fee calculation of §3.5. `base_rental_rate_cents` (the per-copy, per-loan-period rate) and `sale_price_cents` (the per-copy retail price) must both be greater than zero. `license_format` is `PRINT_ONLY`, `DIGITAL_ONLY`, or `PRINT_AND_DIGITAL`: `PRINT_ONLY` excludes digital fulfillment, while `DIGITAL_ONLY` excludes physical-set dispatch. `perusal_allowed` (default true) governs whether perusal or approval copies may be requested, and `rights_class` (default `STANDARD`) is one of `STANDARD`, `GRAND_RIGHTS`, or `RESTRICTED` — the latter two require a cleared rights advisory case before any dispatch, as detailed in §3.9. A work's `status` is `CATALOGED` or `WITHDRAWN`; withdrawal blocks new rental, perusal, and purchase activity while leaving existing loans unaffected. Either status value may be set from either value. Re-cataloging a withdrawn work, repricing it (`base_rental_rate_cents`, `sale_price_cents`), or changing `perusal_allowed` or `rights_class` increments the work's `version`. The works list may be filtered by `publisher_id`.

When a publisher's `out_of_print` flag is set, a sourcing-quote capability — available to `LibraryAdmin` and `LibraryClerk` — estimates procurement time for one of its works. The estimate starts from a base of 45 days, adds 30 days when the work's `rights_class` is `GRAND_RIGHTS`, adds 60 days when it is `RESTRICTED`, and subtracts 15 days when a rental set for the work exists (whether in service or under repair) with a condition grade of `A` or `B`; the result never falls below 7 days. The quote is served for any work regardless of the publisher's current `out_of_print` flag. The quote returns `estimated_days` and `quoted_expiry`, the latter being the current clock instant plus the estimated number of days.

### 3.2. Rental Sets and the Copy Availability Ledger

A RentalSet is the library's physical holding of one work. Its `work_id` ties it to the catalog entry, and `set_code` is a human-readable shelf code unique across the entire library (a duplicate is rejected with `ERR_INVALID_REQUEST`, HTTP 400). `copy_count` records the total physical copies owned, must be at least 1, and is immutable after creation. `replacement_value_cents` is the full-set replacement value, must be greater than zero, and caps damage charges as described in §3.6. Creation initializes `condition_grade` to `A` and `status` to `IN_SERVICE`. `available_copy_count` is a computed ledger field: any client-supplied value at creation is ignored, and it always starts equal to `copy_count`.

The availability ledger keeps `available_copy_count` equal to `copy_count` minus the copies held by the set's rental lines in `RESERVED`, `DISPATCHED`, `ON_LOAN`, `OVERDUE`, or `LOST` status, computed from current line state on every read and never falling below zero. Every allocation decrements it, every returned or released line restores one unit, and a lost line restores nothing — because `LOST` remains in the held set, the copy never comes back. Only `IN_SERVICE` sets whose `condition_grade` is not `D` are allocatable.

Condition governance is shared between the returns desk and administration. `condition_grade` runs from `A` (best) through `D` (worst) and reflects the worst grade observed across the set's returned lines; a set carrying a `D` grade is unrentable until repaired. When a returned line grades `D` at check-in, the set automatically moves from `IN_SERVICE` to `UNDER_REPAIR`. A `LibraryAdmin` may additionally move a set to `UNDER_REPAIR` by hand, mark a repair complete — returning the set from `UNDER_REPAIR` to `IN_SERVICE`, which requires the set to currently be `UNDER_REPAIR` (otherwise `ERR_INVALID_STATE`) and lifts the recorded `condition_grade` above `D` (when the repair-complete request supplies no replacement grade, a recorded `D` lifts to `C` and any higher recorded grade is kept) — or retire a set outright. The same administrative update may also overwrite `condition_grade` directly to any grade; recording a `D` on an `IN_SERVICE` set drops it to `UNDER_REPAIR` automatically. Retirement moves `IN_SERVICE` to the terminal `RETIRED` state and is refused with `ERR_SET_HAS_OPEN_LOANS` while any line of the set remains in `RESERVED`, `DISPATCHED`, `ON_LOAN`, or `OVERDUE`. Each of these mutations increments the set's `version`. The rental-set list may be filtered by `work_id`.

### 3.3. Customer Accounts, Credit Exposure, and Standing

Opening a customer account — done by a `LibraryAdmin` or `BillingManager` — records `account_name`, `account_kind` (`INDIVIDUAL`, `SCHOOL`, or `INSTITUTION`), `credit_tier` (`PREFERRED`, `STANDARD`, or `PREPAY`; default `STANDARD`), `credit_limit_cents` (default 0), and `requires_purchase_order` (default false). Accounts of kind `SCHOOL` or `INSTITUTION` may raise purchase orders and perusal requests; an `INDIVIDUAL` account may not raise purchase orders. A `PREPAY` account must prepay its rentals before dispatch, and its `credit_limit_cents` is forced to 0. New accounts open with `standing` of `GOOD` and both exposure counters at 0. Listing accounts is a staff capability; a `Customer` may read only its own account record.

Two exposure measures are maintained continuously and recomputed on any mutation touching the account's invoices, rentals, or sales. The informational measure, `open_exposure_cents`, sums four components: the `amount_cents` of the account's damage invoices in `DRAFT`, `ISSUED`, or `DISPUTED`; the `estimated_fee_cents` of its rental orders in `RESERVED`, `DISPATCHED`, `ON_LOAN`, or `OVERDUE`; the `final_fee_cents` of its orders in `RETURNED` or `DISPUTED` once that final fee is set; and the `balance_due_cents` of its `INVOICED` sale records. The enforcement measure, `settled_exposure_cents`, uses narrower sets: damage invoices count only when `ISSUED` or `DISPUTED` (drafts are excluded), and rental estimates count only once an order has been dispatched — `DISPATCHED`, `ON_LOAN`, or `OVERDUE` — because a reserved order has not yet created an obligation; returned and disputed orders contribute their final fees, and invoiced sale balances contribute, exactly as in the open variant. The two variants diverge whenever a draft damage invoice or a reserved order exists.

`standing` takes the values `GOOD`, `HOLD`, and `BARRED`. The system flips `GOOD` to `HOLD` when an overdue rental appears, when issuing a damage invoice pushes settled exposure to or beyond a positive credit limit, or when a perusal copy goes overdue. That flip suspends every `APPROVED` purchase order on the account — each such order's `version` increments — and increments the account's own `version`. Standing returns from `HOLD` to `GOOD` automatically once no `OVERDUE` rentals and no `OVERDUE_PERUSAL` perusals remain and settled exposure sits below the credit limit; a credit limit of 0 means no cap is enforced at all. The restoration reinstates each `SUSPENDED` purchase order to `APPROVED` and again increments the account's `version`. Restoration is evaluated whenever an obligation on the account is reduced or cleared — damage-invoice payment, invoice dispute resolution or reissue, sale payment or write-off, rental-order settlement, perusal return — and on every daily sweep; check-in alone does not trigger it. A `BillingManager` may bar a `HOLD` account — barring from any other state is rejected with `ERR_INVALID_STATE` — and may later reinstate a `BARRED` one, provided no overdue rentals or overdue perusals remain (otherwise `ERR_ACCOUNT_STILL_DELINQUENT`); reinstatement restores the account to `GOOD` and returns its suspended purchase orders to `APPROVED`. Any non-`GOOD` standing blocks reservation, dispatch, renewal, purchase-order approval, and perusal approval with `ERR_ACCOUNT_NOT_IN_GOOD_STANDING`.

A `BillingManager` adjusts an account's credit limit by submitting `new_credit_limit_cents` together with the OCC guard field `expected_customer_account_version` described in §2.7. The new limit must be a non-negative integer (else `ERR_INVALID_REQUEST`). A successful adjustment rewrites `credit_limit_cents` and increments the account's `version`.

### 3.4. Purchase Orders and Institutional Encumbrance

A purchase order records `account_id`, the institution's own `po_number` (unique per account), `authorized_amount_cents` (a spending ceiling that must be greater than zero), a computed `encumbered_cents`, and a validity window `valid_from` to `valid_until`, where `valid_until` must be later than `valid_from`. Its `status` walks the states `SUBMITTED`, `APPROVED`, `SUSPENDED`, `EXPIRED`, `CLOSED`, and `REJECTED`. A `Customer` or `BillingManager` submits a purchase order, but only for an account of kind `SCHOOL` or `INSTITUTION` — otherwise the request fails with `ERR_PO_REQUIRES_INSTITUTION` (HTTP 422). A new purchase order starts `SUBMITTED` with `encumbered_cents` at 0. Approval by a `BillingManager` requires the order to be `SUBMITTED` (else `ERR_INVALID_STATE`), the account kind to be institutional, and the account's standing to be `GOOD`; it moves the order to `APPROVED` and increments its `version`. Rejection from `SUBMITTED` moves it to the terminal `REJECTED` state.

`encumbered_cents` is computed from current order state as the sum of the `estimated_fee_cents` of all non-terminal rental orders referencing the purchase order (an order with no stamped estimate contributes nothing). Encumbrance accrues at reservation — the order's estimated fee is added and the purchase order's `version` increments — adjusts by the fee delta at renewal, and is released at settlement or cancellation. When an account's `requires_purchase_order` flag is set, every rental order on that account must carry a `purchase_order_id`; at both reservation and dispatch the referenced purchase order must be `APPROVED` with the current date inside its validity window — `valid_from` and `valid_until` both count as inside — otherwise `ERR_PO_NOT_USABLE`. At reservation, `encumbered_cents` plus the order's new `estimated_fee_cents` must not exceed `authorized_amount_cents`; at renewal the same check runs with the renewed total substituted for the order's previous estimate — `encumbered_cents` minus the current estimate plus the renewed estimate must not exceed the ceiling. A breach is rejected with `ERR_PO_AMOUNT_EXCEEDED` (HTTP 402).

The standing cascade of §3.3 drives the cyclic `APPROVED` ↔ `SUSPENDED` pair: when an account's standing flips from `GOOD` to `HOLD` or `BARRED`, each of its `APPROVED` purchase orders moves to `SUSPENDED`, and when standing returns to `GOOD` each returns to `APPROVED`, every move incrementing that purchase order's `version`. The daily sweep moves an `APPROVED` purchase order past its `valid_until` to `EXPIRED`, but only when no non-terminal rental orders still reference it. A `BillingManager` may close an `APPROVED` purchase order under the same guard — when open orders still reference it the close is refused with `ERR_PO_HAS_OPEN_ORDERS` — moving it to `CLOSED` and incrementing its `version`. The purchase-order list may be filtered by `account_id`.

### 3.5. The Rental Journey from Draft to Return

A `LibraryClerk` or a `Customer` opens a rental order with `account_id`, `rental_set_id`, an optional `purchase_order_id` (mandatory when the account's `requires_purchase_order` flag is set, optional otherwise), `fulfillment_format` (`PHYSICAL` by default, or `DIGITAL`), `copies_requested` (at least 1), `checkout_date`, and `due_date`, which must be later than `checkout_date` or the request fails shape validation with `ERR_INVALID_REQUEST`. The order is born in `DRAFT` with `loan_periods` already computed — the number of 30-day loan periods spanned by the half-open window from `checkout_date` to `due_date`, rounded up, and never less than one — and with `renewal_count` and `prepayment_cents` at 0. Neither fee field exists yet: `estimated_fee_cents` is first stamped at reservation, and `final_fee_cents` remains null until the order is returned. Creation stores the request unchecked: license-format, overlap, standing, and fiscal rules are all deferred to reservation. The order's full status vocabulary is `DRAFT`, `RESERVED`, `DISPATCHED`, `ON_LOAN`, `OVERDUE`, `RETURNED`, `DISPUTED`, `SETTLED`, and `CANCELLED`, with `SETTLED` and `CANCELLED` terminal. Rental orders may be listed with filters on `account_id`, `rental_set_id`, or `purchase_order_id`.

The provisional fee, `estimated_fee_cents`, is computed at reservation and at renewal from exactly three inputs: the order, its work, and its publisher. The per-copy-per-period rate comes from the work's ensemble tier: `CHAMBER` pays `base_rental_rate_cents` unchanged, `BAND` pays one and a half times that base, and `ORCHESTRA` pays double; this tier rate is rounded half-up to whole cents. The gross fee is that tier rate multiplied by `loan_periods` and by `copies_requested`. A volume discount keyed to `copies_requested` then applies: no discount for fewer than ten copies, ten percent for ten through twenty-four copies, and twenty percent for twenty-five copies or more. The publisher's `rental_discount_pct` reduces the remainder, and the resulting net is rounded half-up to whole cents. For `DIGITAL` fulfillment the net is finally multiplied by 0.80 and rounded half-up once more. The rounding order is pinned exactly as written: tier rate first, then the net after both discounts, then the digital factor. While an order is `ON_LOAN` or `OVERDUE`, a settlement-preview capability projects the same formula with `loan_periods` recomputed against the later of `due_date` and the current clock date — so an overdue order projects extended-period fees — returning `projected_fee_cents` and `late_days`; requested in any other state, it fails with `ERR_INVALID_STATE`.

Reservation — a `LibraryClerk` moving the order `DRAFT` → `RESERVED` — runs the gauntlet in the pipeline order of §2.9. The account's standing must be `GOOD` (`ERR_ACCOUNT_NOT_IN_GOOD_STANDING`). The set must be `IN_SERVICE` with a condition grade other than `D` (`ERR_RENTAL_SET_NOT_RENTABLE`). The work must be `CATALOGED` and its publisher `ACTIVE` (`ERR_WORK_NOT_RENTABLE`). `DIGITAL` fulfillment requires the work's `license_format` to be `DIGITAL_ONLY` or `PRINT_AND_DIGITAL` and the publisher's `print_only_rental` flag to be false, else `ERR_LICENSE_FORMAT_NOT_AVAILABLE` (HTTP 422). The requested window must leave at least `copies_requested` allocatable copies on the set: `copy_count` minus the copies held by lines in `RESERVED`, `DISPATCHED`, `ON_LOAN`, or `OVERDUE` whose own windows overlap the request under the half-open rule of §2.10 — a shortfall is `ERR_INSUFFICIENT_COPIES`. This copy-window check runs only for `PHYSICAL` fulfillment; a `DIGITAL` order holds no physical copies at reservation and skips it. When a purchase order is required or referenced, it must be usable with headroom for the new fee (`ERR_PO_NOT_USABLE`, `ERR_PO_AMOUNT_EXCEEDED`). Finally, for accounts that are not `PREPAY`, `settled_exposure_cents` plus the new `estimated_fee_cents` must not exceed `credit_limit_cents` — a credit limit of 0 is treated as uncapped — with breaches returned as `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402); `PREPAY` accounts skip this exposure check at reservation because their payment falls due at dispatch. On success the system allocates: it creates one rental line per requested copy with `copy_seq` running from 1 through `copies_requested`, each line `RESERVED`; decrements the set's `available_copy_count` by `copies_requested`; stamps `estimated_fee_cents`; adds the fee to the referenced purchase order's `encumbered_cents` (incrementing the purchase order's `version`); recomputes both account exposures (incrementing the account's `version`); and increments the order's `version`.

Each rental line carries `rental_order_id`, `copy_seq`, `checkout_condition` (a grade `A` through `D`, stamped `A` when the line is created at reservation), `return_condition` (`A` through `D` or `LOST`, null until the line returns), and a `status` of `RESERVED`, `DISPATCHED`, `ON_LOAN`, `OVERDUE`, `RETURNED`, `LOST`, or `RELEASED`; the line status machine is what drives the availability ledger of §3.2. Lines advance only as a cascade of their parent order's transitions — `RESERVED` to `DISPATCHED` at dispatch, `DISPATCHED` to `ON_LOAN` at receipt confirmation, `ON_LOAN` to `OVERDUE` at the sweep, `ON_LOAN` or `OVERDUE` to `RETURNED` at check-in, and `RESERVED` to `RELEASED` at cancellation — with the exceptions of §3.6's lost-copy report. Rental lines may be listed with a `rental_order_id` filter.

Dispatch — a `LibraryClerk` moving `RESERVED` → `DISPATCHED` — re-verifies the gates: the order must currently be `RESERVED` (`ERR_INVALID_STATE`), standing must still be `GOOD`, a referenced purchase order must still be `APPROVED` (`ERR_PO_NOT_USABLE`), and for works whose `rights_class` is `GRAND_RIGHTS` or `RESTRICTED` there must exist a rights advisory case for this account and work that is `DECIDED` with determination `CLEARED`, else `ERR_RIGHTS_NOT_CLEARED`. For `PREPAY` accounts, dispatch additionally requires `prepayment_cents` to cover the full `estimated_fee_cents`, else `ERR_PREPAYMENT_REQUIRED` (HTTP 402). On dispatch every line moves `RESERVED` → `DISPATCHED` with its `checkout_condition` standing as stamped at reservation, and the order's `version` increments.

Receipt confirmation belongs to the renting `Customer`: the order must be `DISPATCHED`, the acting customer must belong to the order's account (`ERR_FORBIDDEN_ACCOUNT`), and confirmation moves `DISPATCHED` → `ON_LOAN` with every line following, incrementing the order's `version`. Renewal — `ON_LOAN` → `ON_LOAN`, performed by a `LibraryClerk` — is the OCC-guarded write of §2.7 and requires `expected_rental_order_version`. The order must be `ON_LOAN`; the renewal cap admits at most two renewals per order, so a `renewal_count` already at 2 is rejected with `ERR_RENEWAL_CAP_REACHED`; standing must be `GOOD`; the extended window is re-checked for overlap against other orders' live lines on the same set — an order's own lines are excluded from the blocker set, since an order never blocks itself, and this re-check applies to every fulfillment format, `DIGITAL` included — and a collision is `ERR_RENEWAL_CONFLICT`; and a referenced purchase order must still be `APPROVED` with the new total estimated fee inside its ceiling (`ERR_PO_AMOUNT_EXCEEDED`). A successful renewal extends `due_date` by exactly 30 days, recomputes `loan_periods`, increments `renewal_count`, re-estimates the fee by the provisional formula, applies the encumbrance delta to the referenced purchase order (incrementing its `version`), recomputes the account exposures (incrementing the account's `version`), and increments the order's `version`.

When the clock passes an order's `due_date`, the daily sweep moves the order from `ON_LOAN` to `OVERDUE` and every line still `ON_LOAN` with it, flips a `GOOD` account to `HOLD` (incrementing the account's `version`), and — when the order references a purchase order — lets the standing flip cascade that purchase order into `SUSPENDED`, incrementing its `version` as well.

Two smaller operations round out the journey. A `BillingManager` records prepayments against an order in any status: each `amount_cents` must be a positive integer (else `ERR_INVALID_REQUEST`), adds its amount to `prepayment_cents`, and increments the order's `version`. And cancellation by a `LibraryClerk` is permitted only from `DRAFT` or `RESERVED` — any other state is `ERR_ORDER_NOT_CANCELLABLE` — and runs a compensating cascade: any allocated lines move to `RELEASED`, each released line restores one unit of the set's `available_copy_count`, the referenced purchase order's encumbrance is released, both account exposures are recomputed, and the order's `version` increments.

### 3.6. Condition Assessment, Damage Billing, and the Dispute Loop

Return check-in is the `ReturnsClerk`'s exclusive operation. The request carries `line_grades`, a per-line record of observed condition, and applies to orders in `ON_LOAN` or `OVERDUE` — any other state is `ERR_INVALID_STATE`. `line_grades` is accepted polymorphically: a comma-separated grade string or a list of grade strings, applied to the order's returnable lines in `copy_seq` order; a map from line id to grade; or a list of objects naming the line (by `rental_line_id`, `line_id`, or `copy_seq`) and the grade (as `observed_grade`, `return_condition`, or `grade`). Lines not mentioned default to their recorded `checkout_condition`; grades naming unknown lines are ignored; an invalid grade value fails shape validation with `ERR_INVALID_REQUEST`. Check-in moves the order to `RETURNED` and fires the full cascade: every non-lost line moves to `RETURNED` with its `return_condition` recorded from the submitted grades; `final_fee_cents` is computed; each returned line restores one unit of the set's `available_copy_count`; the set's `condition_grade` is reset to the worst grade across all of its returned lines, and if any line came back `D` the set drops from `IN_SERVICE` to `UNDER_REPAIR` with its `version` incrementing; for each line whose observed grade degraded relative to its `checkout_condition`, a condition report is filed in `FILED` status carrying a computed `assessed_charge_cents`; the account's exposures recompute with its `version` incrementing; and the order's `version` increments. An order with no damage proceeds directly toward settlement eligibility.

The final fee builds on the provisional formula evaluated against the final window — renewals are already folded into `due_date`. Lateness is measured in whole calendar days from `due_date` to the return date, where the return date is the logical clock date at check-in, and is never below zero. A daily base is computed exactly once: the final base divided by the product of `loan_periods`, `copies_requested`, and 30, rounded half-up. The late days then split chronologically into tiers — the first seven late days form the first tier, the next twenty-three the second, and any remainder from day thirty-one onward the third — and each tier carries a per-copy-per-day rate derived from the rounded daily base and itself rounded half-up: ten percent of the daily base in the first tier, twenty-five percent in the second, and fifty percent in the third. The surcharge is the sum, over the three tiers, of days-in-tier times the copy count times the tier rate, applied to all copies on the order; `final_fee_cents` is the base plus this surcharge. An on-time return carries no surcharge, so the final equals the provisional base; a late final is always at least the provisional estimate.

Damage pricing distinguishes three cases. Condition grades run from `A` (best) to `D` (worst); when the observed grade is not worse than the line's `checkout_condition`, there is no degradation and `assessed_charge_cents` is 0. When a line's `observed_grade` is `LOST`, the charge is the per-copy replacement value: the set's `replacement_value_cents` divided by its `copy_count`, rounded half-up. For genuine degradation the charge is that same per-copy value — rounded half-up before use — multiplied by a fraction keyed to the grade pair: `A` to `B` at ten percent, `A` to `C` at thirty percent, `A` to `D` at sixty percent, `B` to `C` at twenty-five percent, `B` to `D` at fifty percent, and `C` to `D` at thirty-five percent; the product is rounded half-up, then capped at 200,000 cents by taking the smaller of the raw figure and the cap, then floored at 1,500 cents by taking the larger of the capped figure and the floor.

A `LibraryClerk` may instead report a line lost outright while it is `ON_LOAN` or `OVERDUE` (any other state is `ERR_INVALID_STATE`). The line moves to `LOST`, a condition report is auto-filed with `observed_grade` `LOST` and the per-copy replacement charge, and the set's `available_copy_count` is pointedly not incremented — the copy never returns, and since the held-copy count does not change, the set's `version` does not increment on a lost report.

A condition report records `rental_line_id`, `assessor_user_id` (the `X-User-ID` of the `ReturnsClerk` who performed the assessment, retained for the segregation-of-duties check), `observed_grade` (`A` through `D` or `LOST`), `findings` (free text, required on reports filed through the condition-reports endpoint whenever the observed grade is `C`, `D`, or `LOST` — omitting it there fails shape validation with `ERR_INVALID_REQUEST`; reports auto-filed at check-in or by a lost-copy report carry no findings), the computed `assessed_charge_cents`, and a `status` of `FILED`, `INVOICED`, or `SUPERSEDED`. Beyond check-in, a `ReturnsClerk` may file a fresh report as a re-assessment during a dispute — the filing itself does not verify that a dispute is open, and any existing line may receive a report; it enters `FILED`, is priced by the same damage-charge rule, and later supersedes the original when billing re-issues against it. Condition reports may be listed with a `rental_line_id` filter.

Billing begins when a `BillingManager` creates a damage invoice from a condition report by supplying `rental_line_id` and `condition_report_id`; the report must belong to the named line (else `ERR_INVALID_REQUEST`) but may sit in any status. The invoice opens in `DRAFT` with `amount_cents` taken from the report's assessed charge, `account_id` copied from the rental order for exposure rollup, and `issuer_user_id` capturing the issuing manager when issuance happens; a draft counts only toward `open_exposure_cents`, which recomputes at creation. Issuance moves `DRAFT` → `ISSUED` and enforces segregation of duties: the issuer's `X-User-ID` must differ from the supporting report's `assessor_user_id` on that line, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Issuing moves the supporting report to `INVOICED`, recomputes both exposures — the invoice now counts in each — and, if settled exposure has reached or exceeded a positive credit limit, flips the account's standing to `HOLD` with the purchase-order suspension cascade of §3.3; the account's `version` increments. Damage invoices may be listed with `account_id`, `rental_line_id`, or `condition_report_id` filters. The full invoice status vocabulary is `DRAFT`, `ISSUED`, `PAID`, `DISPUTED`, `RESOLVED_ACCEPTED`, and `RESOLVED_WAIVED`, with the last four forming the terminal and dispute-side states.

From `ISSUED` or `DISPUTED`, a `BillingManager` may record payment, moving the invoice to `PAID`; the amount leaves both exposure sets and the account's `version` increments. Resolving a disputed invoice takes a `resolution` input and is permitted only from `DISPUTED` (`ERR_INVALID_STATE`), under the same segregation-of-duties check as issuance: `ACCEPT`, `ACCEPTED`, or `RESOLVED_ACCEPTED` accept, while `WAIVE`, `WAIVED`, or `RESOLVED_WAIVED` waive — any other value fails shape validation with `ERR_INVALID_REQUEST`. Acceptance moves the invoice to `RESOLVED_ACCEPTED` with the amount standing and exposures recomputing exactly as if it had been paid, while waiver moves it to `RESOLVED_WAIVED`, zeroing the collected amount but preserving the record for audit. Reissue — a `BillingManager` supplying `new_condition_report_id` — likewise applies only from `DISPUTED` and requires a superseding report: one in `FILED` status for the same line carrying a different assessed charge, otherwise `ERR_REASSESSMENT_REQUIRED`. Reissue moves the old report to `SUPERSEDED`, the new report to `INVOICED`, updates `amount_cents` to the new charge, returns the invoice to `ISSUED`, and recomputes exposures with the account's `version` incrementing.

Above the invoices sits the order-level dispute loop. A `Customer` may dispute a `RETURNED` order, which requires at least one `ISSUED` damage invoice on the order's lines (`ERR_NOTHING_TO_DISPUTE`); the dispute moves every such `ISSUED` invoice to `DISPUTED`, moves the order `RETURNED` → `DISPUTED`, and increments the order's `version`. A `BillingManager` closes the loop only when every `DISPUTED` invoice has been resolved — accepted or waived — or re-assessed with its old report superseded and the invoice re-issued; if any `DISPUTED` invoice remains, the close is rejected with `ERR_UNRESOLVED_DISPUTES`. Closing returns the order to `RETURNED` with re-issued invoices resuming `ISSUED`, and increments the order's `version`.

Settlement — a `BillingManager` moving `RETURNED` → `SETTLED` — requires every damage invoice on the order's lines to sit in `PAID`, `RESOLVED_ACCEPTED`, or `RESOLVED_WAIVED`, with none left in `DRAFT`, `ISSUED`, or `DISPUTED` (`ERR_UNSETTLED_DAMAGE_INVOICES`). For `PREPAY` accounts, `final_fee_cents` must be covered by `prepayment_cents` plus whatever damage has been collected — the amounts of the order's invoices in `PAID` or `RESOLVED_ACCEPTED` status — or the settle request must carry a top-up via `topup_cents` (a non-negative integer, else `ERR_INVALID_REQUEST`; a successful top-up is added to `prepayment_cents`); otherwise the settle is rejected with `ERR_PREPAYMENT_SHORTFALL` (HTTP 402). Settlement releases the purchase-order encumbrance — `encumbered_cents` drops by the order's `estimated_fee_cents`, incrementing the purchase order's `version` when one is referenced — recomputes the account exposures, evaluates the standing restoration of §3.3 so that an account with no remaining `OVERDUE` orders and settled exposure under its limit returns from `HOLD` to `GOOD`, and increments both the account's and the order's `version`.

### 3.7. Perusal Copies, Holds, and Conversion

A `Customer` or `LibraryClerk` files a perusal request with `account_id`, `work_id`, and `format` (`PHYSICAL` or `DIGITAL`). Perusals are an institutional privilege: the account must be of kind `SCHOOL` or `INSTITUTION`, both at filing and at approval, otherwise the request fails with `ERR_PERUSAL_REQUIRES_INSTITUTION` (HTTP 422). A new request starts in `REQUESTED`, with `converted_target_kind` reading `NONE` until a conversion happens. The full status vocabulary is `REQUESTED`, `APPROVED`, `SHIPPED`, `OVERDUE_PERUSAL`, `RETURNED`, `CONVERTED`, `EXPIRED`, and `REJECTED`, with `RETURNED`, `CONVERTED`, `EXPIRED`, and `REJECTED` terminal.

Approval by a `LibraryClerk` requires the request to be `REQUESTED` (`ERR_INVALID_STATE`); the work must allow perusal (`perusal_allowed` true), be `CATALOGED`, and belong to an `ACTIVE` publisher — any failure there is `ERR_PERUSAL_NOT_ALLOWED`; a `DIGITAL` format additionally requires the publisher's `allows_digital_perusal` flag and a work `license_format` other than `PRINT_ONLY`, else `ERR_LICENSE_FORMAT_NOT_AVAILABLE`; and the account's standing must be `GOOD`. On top of these, the hold-separation rule of §2.10 applies: no other `APPROVED`, `SHIPPED`, or `OVERDUE_PERUSAL` perusal on the same work may have a hold interval intersecting the new one — the new hold must begin strictly after every existing hold's end, with adjacency forbidden — and a violation is `ERR_PERUSAL_HOLD_CONFLICT`. These checks run in the order named: state admissibility, perusal eligibility, license format, hold separation, standing, and finally the institutional-kind rule, so the surfaced error is always the earliest of those that fails. Approval stamps `ship_date` to the current clock date, sets `return_due_date` exactly twenty-one days later, and reserves the closed hold interval from `hold_start` (equal to `ship_date`) through `hold_end` (the return due date plus the three-day quarantine), a 24-day span in all; the request's `version` increments. Rejection of a `REQUESTED` perusal — again a `LibraryClerk` action — moves it to `REJECTED`.

Shipping by a `LibraryClerk` moves `APPROVED` to `SHIPPED` and increments the request's `version`. From there the daily sweep takes over in two ways: a `SHIPPED` perusal whose `return_due_date` has passed moves to `OVERDUE_PERUSAL` and flips a `GOOD` account to `HOLD`, incrementing the account's `version`; and an `APPROVED` perusal left unshipped for more than ten days moves to `EXPIRED`. A `ReturnsClerk` records the copy's return from either `SHIPPED` or `OVERDUE_PERUSAL` (any other state is `ERR_INVALID_STATE`), moving the request to `RETURNED`; if the account's `HOLD` derived solely from this perusal and no other overdue items remain, standing is restored to `GOOD` with the account's `version` incrementing. Perusal requests may be listed with `account_id` or `work_id` filters.

Conversion — a `LibraryClerk` action on a `SHIPPED` request (any other state is `ERR_INVALID_STATE`) — takes `converted_target_kind` of `RENTAL` or `PURCHASE`. A rental conversion additionally supplies `rental_set_id`, `copies_requested`, `checkout_date`, and `due_date`, and delegates to the full reservation chain of §3.5: every reserve precondition applies, and on success a new rental order appears directly in `RESERVED`, carrying `fulfillment_format` `PHYSICAL`. A purchase conversion requires the account's standing to be `GOOD` and creates a sale record in `INVOICED` carrying the perusal conversion discount, with an optional `quantity` input (default 1) setting the sale's quantity. Either way the perusal moves to `CONVERTED`, `converted_target_id` records the `id` of the created rental order or sale record, and the request's `version` increments.

Conversion pricing is pinned. The perusal conversion discount is fifteen percent off the work's `sale_price_cents`. The discounted per-unit price is rounded half-up first — before any multiplication by quantity — and becomes the sale's `unit_price_cents`; `total_cents` is then that per-unit price multiplied by `quantity`, and `balance_due_cents` starts equal to `total_cents`. Rounding the total after multiplication instead can diverge from the pinned result and is non-conformant.

### 3.8. Retail Sales and Sale Settlement

A sale record captures a purchase with `account_id`, `work_id`, `quantity` (at least 1), the computed `unit_price_cents`, `total_cents`, and `balance_due_cents`, an optional `perusal_request_id`, and a `status` of `INVOICED`, `PAID`, or `WRITTEN_OFF`. A `LibraryClerk` or `BillingManager` may create a direct sale; the fifteen percent conversion discount applies only when `perusal_request_id` is present, and a direct sale without one bills at the full `sale_price_cents` per copy. Every new sale opens `INVOICED` with `balance_due_cents` equal to `total_cents`, and the account's exposures recompute at creation. Sale records may be listed with `account_id`, `work_id`, or `perusal_request_id` filters.

From `INVOICED`, a `BillingManager` may record payment — moving the sale to `PAID`, zeroing `balance_due_cents`, and recomputing the account exposures — or write the sale off, moving it to the terminal `WRITTEN_OFF` state, likewise zeroing `balance_due_cents` as written off and recomputing exposures. Payment recording from any state other than `INVOICED` is rejected with `ERR_INVALID_STATE`; both paths increment the account's `version`.

### 3.9. Performance-Rights Advisory

Works whose `rights_class` is `GRAND_RIGHTS` or `RESTRICTED` may not be dispatched until a rights advisory case for the same account and work has been decided `CLEARED`; `STANDARD` works need no case at all. A `Customer`, `LibraryClerk`, or `RightsAdvisor` opens a case with `account_id`, `work_id`, `venue_kind` — one of `EDUCATIONAL`, `CONCERT`, `COMPETITION`, or `RELIGIOUS`, classifying the venue so the determination can weigh it — and a free-text `question`. A new case opens in `OPEN` with `determination` reading `PENDING`. The determination vocabulary is `PENDING`, `CLEARED`, `LICENSE_REQUIRED`, and `PROHIBITED`; the case `status` vocabulary is `OPEN`, `DECIDED`, and `WITHDRAWN`, the latter two terminal.

A `RightsAdvisor` decides an `OPEN` case (any other state is `ERR_INVALID_STATE`) by supplying a `determination` of `CLEARED`, `LICENSE_REQUIRED`, or `PROHIBITED` — any other value fails shape validation with `ERR_INVALID_REQUEST`. The decision records `decided_by_user_id` from the advisor's `X-User-ID`, moves the case to `DECIDED`, and increments its `version`. Only a case that is both `DECIDED` and determined `CLEARED` satisfies the dispatch gate of §3.5. The owning `Customer` may instead withdraw an `OPEN` case; the acting customer must belong to the case's account, otherwise `ERR_FORBIDDEN_ACCOUNT`. Cases may be listed with `account_id` or `work_id` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all state transitions — return `200 OK`. The table below is a routing summary only: request payloads, response shapes, preconditions, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/library/_clock/set_current_utc` | Set the logical clock | LibraryAdmin |
| POST | `/library/_sweep/run_daily` | Run the daily batch sweep | LibraryAdmin |
| POST | `/library/publishers` | Create a publisher | LibraryAdmin |
| GET | `/library/publishers` | List publishers | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/publishers/{id}` | Get a publisher | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| PATCH | `/library/publishers/{id}` | Update publisher flags or suspend/reactivate | LibraryAdmin |
| POST | `/library/works` | Catalog a work | LibraryAdmin |
| GET | `/library/works` | List works | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/works/{id}` | Get a work | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/works/{id}/sourcing-quote` | Out-of-print sourcing ETA quote | LibraryAdmin, LibraryClerk |
| PATCH | `/library/works/{id}` | Withdraw or re-catalog a work, or update pricing | LibraryAdmin |
| POST | `/library/rental-sets` | Create a rental set for a work | LibraryAdmin |
| GET | `/library/rental-sets` | List rental sets | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/rental-sets/{id}` | Get a rental set | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| PATCH | `/library/rental-sets/{id}` | Repair-complete / retire / condition override | LibraryAdmin |
| POST | `/library/customer-accounts` | Open a customer account | LibraryAdmin, BillingManager |
| GET | `/library/customer-accounts` | List accounts | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor |
| GET | `/library/customer-accounts/{id}` | Get an account (Customer may read only its own) | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| POST | `/library/customer-accounts/{id}/credit-adjustments` | Manually adjust the credit limit (OCC-guarded) | BillingManager |
| POST | `/library/customer-accounts/{id}/bar` | Bar a HOLD account | BillingManager |
| POST | `/library/customer-accounts/{id}/reinstate` | Reinstate a BARRED account | BillingManager |
| POST | `/library/purchase-orders` | Submit a purchase order | Customer, BillingManager |
| GET | `/library/purchase-orders` | List purchase orders | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/purchase-orders/{id}` | Get a purchase order | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| POST | `/library/purchase-orders/{id}/approve` | Approve a submitted purchase order | BillingManager |
| POST | `/library/purchase-orders/{id}/reject` | Reject a submitted purchase order | BillingManager |
| POST | `/library/purchase-orders/{id}/close` | Close an APPROVED purchase order with no open orders | BillingManager |
| POST | `/library/rental-orders` | Create a rental order in DRAFT | LibraryClerk, Customer |
| GET | `/library/rental-orders` | List rental orders | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/rental-orders/{id}` | Get a rental order | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/rental-orders/{id}/settlement-preview` | Projected final fee for an ON_LOAN/OVERDUE order | LibraryAdmin, LibraryClerk, BillingManager, Customer |
| POST | `/library/rental-orders/{id}/reserve` | Reserve copies (DRAFT to RESERVED) | LibraryClerk |
| POST | `/library/rental-orders/{id}/dispatch` | Dispatch a reserved order (RESERVED to DISPATCHED) | LibraryClerk |
| POST | `/library/rental-orders/{id}/confirm-receipt` | Customer confirms receipt (DISPATCHED to ON_LOAN) | Customer |
| POST | `/library/rental-orders/{id}/renew` | Renew an ON_LOAN order (OCC-guarded) | LibraryClerk |
| POST | `/library/rental-orders/{id}/check-in` | Return check-in with per-line condition grades | ReturnsClerk |
| POST | `/library/rental-orders/{id}/dispute` | Customer disputes damage invoices (RETURNED to DISPUTED) | Customer |
| POST | `/library/rental-orders/{id}/resolve-dispute` | Close the dispute loop (DISPUTED to RETURNED) | BillingManager |
| POST | `/library/rental-orders/{id}/settle` | Settle a returned order (RETURNED to SETTLED) | BillingManager |
| POST | `/library/rental-orders/{id}/cancel` | Cancel a DRAFT or RESERVED order | LibraryClerk |
| POST | `/library/rental-orders/{id}/prepayments` | Record a prepayment (PREPAY accounts) | BillingManager |
| GET | `/library/rental-lines` | List rental lines | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager |
| GET | `/library/rental-lines/{id}` | Get a rental line | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager |
| POST | `/library/rental-lines/{id}/report-lost` | Report a copy lost | LibraryClerk |
| GET | `/library/condition-reports` | List condition reports | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager |
| GET | `/library/condition-reports/{id}` | Get a condition report | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager |
| POST | `/library/condition-reports` | File a re-assessment during a dispute | ReturnsClerk |
| POST | `/library/damage-invoices` | Create a DRAFT damage invoice from a filed condition report | BillingManager |
| GET | `/library/damage-invoices` | List damage invoices | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, Customer |
| GET | `/library/damage-invoices/{id}` | Get a damage invoice | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, Customer |
| POST | `/library/damage-invoices/{id}/issue` | Issue a DRAFT invoice (segregation of duties enforced) | BillingManager |
| POST | `/library/damage-invoices/{id}/record-payment` | Record payment of an ISSUED or DISPUTED invoice | BillingManager |
| POST | `/library/damage-invoices/{id}/resolve` | Resolve a disputed invoice (accept or waive) | BillingManager |
| POST | `/library/damage-invoices/{id}/reissue` | Re-issue a disputed invoice against a superseding re-assessment | BillingManager |
| POST | `/library/perusal-requests` | Request a perusal / approval copy | Customer, LibraryClerk |
| GET | `/library/perusal-requests` | List perusal requests | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/perusal-requests/{id}` | Get a perusal request | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| POST | `/library/perusal-requests/{id}/approve` | Approve a perusal (reserves the buffered hold interval) | LibraryClerk |
| POST | `/library/perusal-requests/{id}/reject` | Reject a perusal request | LibraryClerk |
| POST | `/library/perusal-requests/{id}/ship` | Mark a perusal shipped | LibraryClerk |
| POST | `/library/perusal-requests/{id}/record-return` | Record a perusal copy return | ReturnsClerk |
| POST | `/library/perusal-requests/{id}/convert` | Convert a perusal to a rental or purchase | LibraryClerk |
| POST | `/library/sale-records` | Create a direct sale (no perusal) | LibraryClerk, BillingManager |
| GET | `/library/sale-records` | List sale records | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, Customer |
| GET | `/library/sale-records/{id}` | Get a sale record | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, Customer |
| POST | `/library/sale-records/{id}/record-payment` | Record a sale payment | BillingManager |
| POST | `/library/sale-records/{id}/write-off` | Write off an unpaid sale | BillingManager |
| POST | `/library/rights-advisory-cases` | Open a performance-rights advisory case | Customer, LibraryClerk, RightsAdvisor |
| GET | `/library/rights-advisory-cases` | List advisory cases | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| GET | `/library/rights-advisory-cases/{id}` | Get an advisory case | LibraryAdmin, LibraryClerk, ReturnsClerk, BillingManager, RightsAdvisor, Customer |
| POST | `/library/rights-advisory-cases/{id}/decide` | Issue a rights determination | RightsAdvisor |
| POST | `/library/rights-advisory-cases/{id}/withdraw` | Withdraw an open case | Customer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the authoritative ID-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_FORBIDDEN_ACCOUNT` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_PUBLISHER_NOT_FOUND` | 404 |
| `ERR_WORK_NOT_FOUND` | 404 |
| `ERR_RENTAL_SET_NOT_FOUND` | 404 |
| `ERR_PO_NOT_FOUND` | 404 |
| `ERR_RENTAL_ORDER_NOT_FOUND` | 404 |
| `ERR_RENTAL_LINE_NOT_FOUND` | 404 |
| `ERR_CONDITION_REPORT_NOT_FOUND` | 404 |
| `ERR_DAMAGE_INVOICE_NOT_FOUND` | 404 |
| `ERR_PERUSAL_REQUEST_NOT_FOUND` | 404 |
| `ERR_SALE_RECORD_NOT_FOUND` | 404 |
| `ERR_RIGHTS_CASE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_RIGHTS_NOT_CLEARED` | 409 |
| `ERR_LICENSE_FORMAT_NOT_AVAILABLE` | 422 |
| `ERR_RENTAL_SET_NOT_RENTABLE` | 409 |
| `ERR_WORK_NOT_RENTABLE` | 409 |
| `ERR_INSUFFICIENT_COPIES` | 409 |
| `ERR_RENEWAL_CONFLICT` | 409 |
| `ERR_PERUSAL_HOLD_CONFLICT` | 409 |
| `ERR_PO_NOT_USABLE` | 409 |
| `ERR_PO_AMOUNT_EXCEEDED` | 402 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_PREPAYMENT_REQUIRED` | 402 |
| `ERR_PREPAYMENT_SHORTFALL` | 402 |
| `ERR_ACCOUNT_NOT_IN_GOOD_STANDING` | 409 |
| `ERR_ACCOUNT_STILL_DELINQUENT` | 409 |
| `ERR_PO_REQUIRES_INSTITUTION` | 422 |
| `ERR_PERUSAL_REQUIRES_INSTITUTION` | 422 |
| `ERR_PERUSAL_NOT_ALLOWED` | 409 |
| `ERR_RENEWAL_CAP_REACHED` | 409 |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 |
| `ERR_NOTHING_TO_DISPUTE` | 409 |
| `ERR_UNSETTLED_DAMAGE_INVOICES` | 409 |
| `ERR_UNRESOLVED_DISPUTES` | 409 |
| `ERR_REASSESSMENT_REQUIRED` | 409 |
| `ERR_PO_HAS_OPEN_ORDERS` | 409 |
| `ERR_SET_HAS_OPEN_LOANS` | 409 |
