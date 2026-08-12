# Propane Cylinder Exchange API — Product Requirements Document

## 1. Introduction

Neighborhood retail partners — hardware stores, fuel stations, garden centers — move propane through two distinct counter motions. The first is the cage swap: a customer hands over an empty cylinder and walks away with a full one. The second is the metered refill: a customer-owned bottle is weighed on arrival, filled, weighed again, and charged by the pound. Both motions live inside a demanding regulatory envelope. Cylinders carry stamped certification dates that expire and must be recertified or condemned under a two-signature safety protocol. Drivers operate under DOT medical cards and vehicle payload law. A single confirmed leak can shut down a site's sales within minutes and force the entire cage into quarantine. And every dollar crossing the drawer must reconcile against the book at close of business, because host sites earn a tiered commission on the sales they ring up — a commission that shrinks when leaks are confirmed on their watch.

This document specifies the Propane Cylinder Exchange API, the back-office and point-of-sale surface governing host-site configuration and pricing, cylinder registration and certification, exchange and refill sales, leak response and quarantine, restock routing between the depot and retail sites, commission settlement, and daily cash reconciliation. Every date-dependent rule in this document — certification sweeps, pricing windows, refund windows, statement periods, planned delivery dates — is evaluated against a logical clock rather than wall-clock time, so that behavior is fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `PlatformAdmin`, `SiteClerk`, `Driver`, `Technician`, `ComplianceOfficer`, and `HostSiteManager`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the target operation — including ownership violations described below — is rejected with `ERR_FORBIDDEN`.

The identity carried by `X-User-ID` differs by role, and the distinction is binding:

- When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on any resource that references a `Driver` — most importantly a restock run's assigned driver — compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; it is recorded as the `technician_id` of any certification record the technician authors and as the `confirmer_technician_id` of any condemn decision they second.
- When `X-User-Role` is `HostSiteManager`, `X-User-ID` is the `id` of the acting `HostSite`; ownership checks compare a resource's site reference to `X-User-ID`, so a host-site manager sees and acts on only their own site.
- When `X-User-Role` is `PlatformAdmin`, `SiteClerk`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `clerk_id` on an exchange order, refill ticket, or reconciliation session, as `reporter_clerk_id` on a leak report, or as `confirmed_by`, `resolved_by`, `verified_by`, or `escalated_by` on the resources those actions touch — but it does not compare it to any entity's `id`. These recorded identities still anchor segregation-of-duties comparisons between actors.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system — host sites, pricing policies, drivers, technicians, cylinders, exchange orders, refill tickets, certification records, leak reports, restock runs, commission statements, and reconciliation sessions — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 and increments by exactly one on every mutation of that row, including mutations driven by cascades.

Alongside wall-clock-free timestamps, the platform runs a **logical clock** that governs every business date in the system. At startup — before any operator action — the logical clock reads exactly `2026-05-01T00:00:00Z`; it is never seeded from wall-clock time. A `PlatformAdmin` advances it through an administrative capability that accepts a `to_iso8601` instant and reports the resulting `current_utc`. All calendar-date fields on resources — every field whose name ends in `_on` or `_date`, such as `business_date`, `performed_on`, and `planned_date` — are ISO calendar dates derived from this logical clock. Advancing the clock triggers the certification sweep described in §3.2: every cylinder whose `cert_status` is `CERTIFIED` and whose `certification_expires_on` is strictly before the new current date flips to `RECERT_DUE`. On the calendar date equal to `certification_expires_on` itself the cylinder remains `CERTIFIED` through end of day; the sweep is strictly-greater only.

### 2.5. Money, Weight, and Rounding Discipline

All monetary values in the system are carried as integer cents. Wherever a money figure is computed rather than supplied — tax, per-tier propane charges, per-sale commissions — the computed value is rounded half-up to whole cents. Rates are expressed in basis points, that is, hundredths of a percent; applying a basis-point rate to a cent amount means multiplying by the rate and dividing by ten thousand.

All weights are carried in pounds with exactly two decimal places, and any computed weight — the propane dispensed on a refill, the maximum legal fill of a cylinder — is rounded half-up to two decimal places. Two multiplication-stage rounding rules are easy to get wrong and are therefore stated here as system-wide doctrine: refill charges are rounded per tier **before** the tiers are summed, and commissions are rounded per sale **before** the per-sale amounts are summed. Sales tax, by contrast, is rounded exactly once, on the whole subtotal.

### 2.6. Optimistic Concurrency Control on Site Configuration

Three write operations are guarded by optimistic concurrency control against the host site's `version`: creating a restock run, creating a pricing policy, and patching a site's configuration or status. Each of these requests must carry `expected_site_version`, a non-optional input field holding the site's `version` as the client last observed it. If the value does not match the site's current `version` — because another accepted write has advanced the site since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). All three guarded writes themselves advance the host site's `version` by one when they succeed, alongside refreshing `updated_at`. No other endpoint accepts a version field; every remaining write is processed without an OCC check.

### 2.7. Request Evaluation Order

Incoming requests are validated against a fixed, fourteen-stage evaluation order; the first stage that fails determines the rejection, and later stages are not consulted. The order is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the six declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role is permitted for the endpoint and ownership rules hold — a driver acts only on their own runs, a host-site manager only on their own site, a clerk never registers a fleet cylinder, and a technician's `cert_level` gates the hydrostatic method and condemn requests; otherwise `ERR_FORBIDDEN`.
3. **Path existence.** Resource identifiers appearing in the URL path exist, validated left to right, so the first missing identifier in the path is the one reported; otherwise `ERR_NOT_FOUND`.
4. **Body reference existence.** Identifiers referenced in the request body — `site_id`, `cylinder_id`, `driver_id`, `returned_cylinder_id` — resolve to existing resources; otherwise `ERR_REFERENCE_NOT_FOUND`.
5. **Optimistic concurrency.** Where §2.6 applies, `expected_site_version` matches the site's current `version`; otherwise `ERR_STALE_VERSION`.
6. **State legality.** The target resource is in a valid from-state for the requested transition, terminal states are locked against further action, the site is `ACTIVE` for sales and dispatch (`ERR_SITE_NOT_ACTIVE`), and a driver's arrival date matches the run's planned date; otherwise `ERR_INVALID_STATE`.
7. **Cylinder safety.** A condemned or quarantined cylinder is rejected before any other business check — `ERR_CYLINDER_CONDEMNED` where a condemned cylinder is offered for filling, return-acceptance, or new certification, `ERR_CYLINDER_QUARANTINED` where handling requires a non-quarantined cylinder, and `ERR_CYLINDER_NOT_CERTIFIED` when a quarantined cylinder is released without current certification.
8. **Certification currency for regulated handling.** A refill fill requires the cylinder to be `CERTIFIED`; a `RECERT_DUE` cylinder is rejected with `ERR_CYLINDER_NOT_CERTIFIED`.
9. **Site sales posture and DOT gates.** A leak-blocked site refuses new sales (`ERR_SALES_BLOCKED`), and dispatch refuses an expired driver medical card (`ERR_DRIVER_CERT_EXPIRED`) or an overloaded vehicle (`ERR_DOT_PAYLOAD_EXCEEDED`).
10. **Temporal windows.** A new pricing policy's window may not begin in the past (`ERR_POLICY_WINDOW_IN_PAST`), and a commission period must be fully closed before finalization (`ERR_PERIOD_NOT_CLOSED`).
11. **Uniqueness, overlap, and magnitude constraints.** Pricing half-open windows per site, one draft restock run per site, one open leak per site, one reconciliation session per site and business date, one run per driver per planned date, serial-number and license uniqueness, idempotency-key reuse, refillability, tare tolerance, overfill, route non-emptiness, selector stock, and decommission emptiness — each reported with its dedicated error from §5.
12. **Cross-entity state gates.** Commission finalization requires every period date reconciled (`ERR_RECONCILIATION_UNRESOLVED`), a refund requires same-day business date with the day's reconciliation still open (`ERR_REFUND_WINDOW_CLOSED`), leak resolution requires re-inspection evidence (`ERR_REINSPECTION_REQUIRED`), and sales require a current pricing policy (`ERR_NO_ACTIVE_POLICY`).
13. **Payment sufficiency.** Tendered cash must equal or exceed the order or ticket total; otherwise `ERR_INSUFFICIENT_PAYMENT`.
14. **Segregation of duties.** The second-signature and resolver checks — restock verifier against run driver, reconciliation resolver against shift clerk, condemn confirmer or rejecter against requesting technician, leak resolver against reporter — run last and reject with `ERR_SEGREGATION_OF_DUTIES`.

### 2.8. Cage Inventory Accounting and Sales Posture

Every host site exposes three live cage counts, computed on read rather than stored. `full_on_hand` is the number of cylinders that are fleet-owned (`owner_kind` `FLEET`), physically at the site (`current_site_id` equals the site), not assigned to a dispatched run (`in_transit_run_id` null), in `fill_status` `FULL`, and not condemned. `empty_on_hand` applies the same filter with `fill_status` `EMPTY`, and `quarantined_on_hand` the same filter with `fill_status` `QUARANTINED`. Customer-owned cylinders never appear in any of the three counts, and condemned cylinders are excluded from all three regardless of fill state. Because the counts are computed, any cylinder mutation touching `current_site_id`, `in_transit_run_id`, `fill_status`, `cert_status`, or `owner_kind` re-derives them — cylinder registration itself never mutates the site row.

Two derived site signals ride on these counts. `reorder_floor_full` is the site's `par_level_full` multiplied by one-half and rounded up to a whole cylinder, and `restock_alert` is true exactly when `full_on_hand` is less than or equal to `reorder_floor_full` — the threshold is inclusive. `sales_posture` is `SALES_BLOCKED` whenever the site has a leak report in `CONFIRMED` status whose `severity` is `MAJOR` or whose `quarantine_cage` flag is true, and `SALES_OPEN` otherwise; a blocked posture refuses new sales with `ERR_SALES_BLOCKED`. Notably, a cylinder whose certification has lapsed into `RECERT_DUE` still counts toward `full_on_hand` — it occupies the cage — even though, as §3.3 specifies, it can never be selected for sale.

### 2.9. Sale Sequencing, Business Dates, and Idempotent Intake

Every completed sale at a site — an exchange completion or a refill close — is stamped with two values drawn from shared machinery. `business_date` is the current logical calendar date at the moment of completion or close. `sale_seq` is drawn from a single per-site, monotonically increasing counter shared by exchange completions and refill closes, so the interleaving of swaps and refills within a day is preserved in one sequence. Both fields are null until the sale completes.

Two intake endpoints accept a client-supplied `idempotency_key`: exchange order creation and reconciliation session creation. The key is unique per clerk. Replaying a key with the identical payload returns the original resource without creating a duplicate; reusing the same key with a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT`.

## 3. Business Logic & Workflows

### 3.1. Host Sites: Onboarding, Configuration, Pricing, and Decommissioning

A `PlatformAdmin` onboards a retail partner by creating a host site. The required identity fields are a display `name` and the cage geometry: `cage_capacity_cylinders`, which must be greater than zero, and `par_level_full`, the desired full-cylinder stock level, which must be at least one and no more than the cage capacity. The commission configuration is captured up front as well: `commission_rate_bps`, between zero and three thousand basis points; `commission_tier_threshold_cents`, the cumulative base above which a marginal bonus rate applies, defaulting to 100,000 cents (one thousand dollars) when omitted; `commission_tier2_bonus_bps`, the additional basis points applied marginally above that threshold, defaulting to 100; and `commission_basis`, either `GROSS` or `NET`, defaulting to `GROSS`. The reconciliation variant is chosen through `recon_basis`, either `BOOK` or `PHYSICAL`, defaulting to `BOOK`. Financial defaults round out the record: `address` defaults to empty, `opening_float_cents` — the declared cash drawer float — defaults to 20,000 cents, `hazmat_fee_cents` defaults to zero, and `promo_waives_hazmat` defaults to false. A new site begins `ACTIVE`, with all three cage counts at zero and `sales_posture` `SALES_OPEN`.

Site configuration evolves through an OCC-guarded patch (§2.6) that may adjust any of the configuration fields above and also drives the site's status machine. From `ACTIVE` a site may be suspended to `SUSPENDED`, and from `SUSPENDED` it may be reactivated to `ACTIVE`; each transition increments the site's `version` by one. Decommissioning is one-way and only available from `SUSPENDED`: the site may transition to `DECOMMISSIONED` only when the cage is completely empty — `full_on_hand`, `empty_on_hand`, and `quarantined_on_hand` all zero — and when no restock run for the site sits in `DRAFT`, `DISPATCHED`, `IN_PROGRESS`, or `COMPLETED`; a run already `VERIFIED` or `CANCELLED` does not block. Violating either condition is rejected with `ERR_SITE_NOT_EMPTY`. Sales and dispatch operations at a site that is not `ACTIVE` are refused with `ERR_SITE_NOT_ACTIVE`.

Pricing for a site is governed by a chain of pricing policies. Each policy carries `swap_price_cents` (non-negative), `core_deposit_cents` (non-negative), `tax_rate_bps` (between zero and two thousand basis points), the refill ladder `refill_tier1_cents_per_lb`, `refill_tier1_max_lbs` (greater than zero, two decimal places), and `refill_tier2_cents_per_lb`, plus a half-open effectiveness window: `effective_from` is inclusive, `effective_to` exclusive, and a null `effective_to` means the window is open-ended. A policy's `is_current` flag is derived: it is true exactly when `effective_from` is on or before the current logical date and either `effective_to` is null or the current date is strictly before `effective_to`. Creating a policy is OCC-guarded by `expected_site_version` and advances the site's `version`. The new `effective_from` may not be strictly before the current logical date, else `ERR_POLICY_WINDOW_IN_PAST`. Windows for the same site may not overlap; an overlapping create is rejected with `ERR_POLICY_WINDOW_OVERLAP`, although adjacency — one window's `effective_to` equal to the next window's `effective_from` — is permitted. A deliberate supersede path exists: creating a policy with `supersede_current` set to true clips the current policy's `effective_to` to the new policy's `effective_from`, and this path requires the new `effective_from` to be strictly later than the current policy's `effective_from`, else the create is rejected with `ERR_POLICY_WINDOW_OVERLAP`. Whenever a site has no current policy at the present logical date, sales at that site are refused with `ERR_NO_ACTIVE_POLICY`.

### 3.2. Cylinder Registration and the Certification Cycle

Every cylinder entering the ecosystem is registered once, by `serial_number` — a stamped serial unique across all cylinders, with duplicates rejected as `ERR_VALIDATION`. Registration records `owner_kind` (`FLEET` or `CUSTOMER`), the stamped `water_capacity_lbs` and `tare_weight_lbs` (each greater than zero, two decimal places), the collar-stamped `manufacture_date`, and an `initial_fill` of `FULL` or `EMPTY` that becomes the cylinder's initial `fill_status`. Fleet cylinders may optionally be registered directly into a site's cage through `current_site_id`; customer cylinders must always be registered with `current_site_id` null, since a customer bottle lives with its owner — a customer cylinder created with a site is rejected with `ERR_VALIDATION`. Fleet registration is restricted to `PlatformAdmin`; a `SiteClerk` attempting to register a fleet cylinder is rejected with `ERR_FORBIDDEN`, as clerks may register customer cylinders only. Registration also initializes the certification ledger on the cylinder itself: `cert_status` begins `CERTIFIED`, `certified_on` is set to the `manufacture_date`, `cert_method_last` begins `INITIAL`, and `certification_expires_on` is the manufacture date advanced by twelve years.

Certification ages in two ways. Passively, the clock-advance sweep of §2.4 moves a cylinder from `CERTIFIED` to `RECERT_DUE` the first day its `certification_expires_on` lies strictly in the past. Actively, a `Technician` records a certification outcome. Recording requires the technician to be `ACTIVE`, and the `method` — `VISUAL` or `HYDROSTATIC` — is gated by the technician's `cert_level`: the `HYDROSTATIC` method requires `FULL` certification, and a `VISUAL_ONLY` technician attempting it is rejected with `ERR_FORBIDDEN`. A `PASS` outcome is immediately effective: the record lands in `RECORDED` status, `performed_on` is stamped with the current logical date, the cylinder's prior expiry is snapshotted into `previous_expires_on`, and `new_expires_on` is computed as `performed_on` advanced by five years for a `VISUAL` recertification or seven years for a `HYDROSTATIC` one. The cylinder's `certified_on`, `certification_expires_on`, and `cert_method_last` are updated to match, and its `cert_status` becomes `CERTIFIED` — this holds both for a voluntary recertification of an already-`CERTIFIED` cylinder and for curing a `RECERT_DUE` one. An optional free-text `note` may accompany the record.

Condemnation is deliberately heavier. Only a technician with `cert_level` `FULL` may request a condemn — a `VISUAL_ONLY` request is rejected with `ERR_FORBIDDEN` — and the request does not take effect: it creates a record in `PENDING_SECOND` status awaiting a second signature. A second technician, who must be `ACTIVE`, must hold `cert_level` `FULL`, and must not be the requesting technician, either confirms or rejects the decision; a confirmer or rejecter equal to the original `technician_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Confirmation additionally requires the cylinder not already be condemned, else `ERR_CYLINDER_CONDEMNED`. On confirmation the record becomes `CONFIRMED`, `confirmer_technician_id` is set, and a three-hop cascade fires: first the cylinder's `cert_status` becomes `CONDEMNED`; second, because the cylinder has left the sellable population, its former site's cage counts recompute; third, if the cylinder had been `FULL` at a site and the recomputed `full_on_hand` now sits at or below the site's `reorder_floor_full`, the site's `restock_alert` flips to true. On rejection the record becomes `REJECTED`, `confirmer_technician_id` is likewise set, and the cylinder is untouched. Condemnation is terminal: a `CONDEMNED` cylinder can never be filled, accepted as a return, or certified again — any such attempt is rejected with `ERR_CYLINDER_CONDEMNED`.

### 3.3. The Exchange Counter: Swap Sales, Completion, and Refunds

The everyday sale is the swap. A `SiteClerk` opens an exchange order with a payload containing the `site_id`, an optional `returned_cylinder_id` identifying the empty the customer hands over, and an optional `idempotency_key` governed by §2.9. Creation is gated by the site's operating posture: the site must be `ACTIVE` (else `ERR_SITE_NOT_ACTIVE`), its `sales_posture` must be `SALES_OPEN` (else `ERR_SALES_BLOCKED`), a current pricing policy must exist (else `ERR_NO_ACTIVE_POLICY`), and if a returned cylinder is offered it must exist (else `ERR_REFERENCE_NOT_FOUND`) and must not be condemned (else `ERR_CYLINDER_CONDEMNED`). The creating clerk's `X-User-ID` is recorded as `clerk_id`. Prices are pinned at creation from the site's current policy: `unit_price_cents` is the policy's `swap_price_cents`; `core_deposit_cents` is zero when the customer hands over a cylinder and the policy's `core_deposit_cents` otherwise; `tax_cents` is the subtotal — unit price plus core deposit — multiplied by the policy's `tax_rate_bps` and divided by ten thousand, rounded half-up once to whole cents; and `total_cents` is the subtotal plus the tax. The order stands in `DRAFT` status.

Completion is where stock and cash move. The clerk tenders `payment_cash_cents`, which must equal or exceed `total_cents`, else the completion is rejected with `ERR_INSUFFICIENT_PAYMENT`. The system then selects the cylinder to issue using the cage selector: candidates are fleet-owned, `CERTIFIED`, `FULL` cylinders physically at the order's site and not in transit; they are ranked by `certified_on` ascending — oldest-certified first — with ties broken by `created_at` ascending; and the first candidate is issued. An empty candidate set rejects the completion with `ERR_NO_STOCK`. Because the selector requires `CERTIFIED` while the cage count of §2.8 merely excludes the condemned, a cage can report stock on hand yet be unable to sell — `RECERT_DUE` cylinders are visible in `full_on_hand` but invisible to the selector. On success the issued cylinder's `id` is recorded as `issued_cylinder_id` and its `current_site_id` is cleared to null — it is with the customer — so the site's `full_on_hand` drops by one. If a `returned_cylinder_id` was supplied, that cylinder is absorbed into the fleet: its `owner_kind` becomes `FLEET`, its `current_site_id` becomes the order's site, its `fill_status` is `EMPTY`, and the site's `empty_on_hand` rises by one. The order's `business_date` and `sale_seq` are stamped per §2.9, `change_due_cents` is computed as the tendered cash minus `total_cents`, the order lands in `COMPLETED`, and the site's open reconciliation session, if one exists for the current date, has its `expected_cash_cents` recomputed to include the order's `total_cents` as a cash addition.

Two exit paths exist before and after completion. A `DRAFT` order may be voided by the clerk; voiding captures no cash — none was taken — and stamps `void_reason` `MANUAL`. A `COMPLETED` order may instead be refunded, but the refund window is deliberately tight: the order's `business_date` must equal the current logical date, and the site's reconciliation session for today, if one exists, must still be in `OPEN` or `VARIANCE_FLAGGED`; either violation is rejected with `ERR_REFUND_WINDOW_CLOSED`, as is any refund attempt on an order not in `COMPLETED` (via `ERR_INVALID_STATE`). A refund stamps `refunded_on` with the current date, moves the order to `REFUNDED`, and sends the issued cylinder back to the site in `fill_status` `QUARANTINED` pending returned-goods inspection — the site's counts and `restock_alert` recompute accordingly — while the day's open reconciliation session recomputes `expected_cash_cents` to include the order's `total_cents` as a cash subtraction. Exchange orders may be listed filtered by `site_id`, `status`, `business_date`, `issued_cylinder_id`, or `returned_cylinder_id`.

### 3.4. The Refill Bay: Weighing, Filling, and Closing

Refills serve customer-owned bottles only. A `SiteClerk` opens a refill ticket with the `site_id`, the `cylinder_id`, and the `pre_weight_lbs` scale reading of the cylinder as received, recorded with two decimal places. The referenced cylinder must exist (else `ERR_REFERENCE_NOT_FOUND`) and must be `owner_kind` `CUSTOMER` — opening a ticket against a fleet cylinder is rejected with `ERR_NOT_REFILLABLE`. The same site gates as the exchange counter apply: the site must be `ACTIVE` and not sales-blocked, and a current pricing policy must exist. At creation the system computes `max_fill_lbs`, the legal fill ceiling: the cylinder's stamped `water_capacity_lbs` multiplied by 0.42, rounded half-up to two decimal places. The ticket opens in `OPEN` status.

Weighing verifies the bottle against its stamp. The clerk records `measured_tare_lbs`, the empty-scale reading; the ticket advances from `OPEN` to `WEIGHED` only if the absolute deviation between `measured_tare_lbs` and the cylinder's stamped `tare_weight_lbs` does not exceed one-tenth of a pound, and only if `pre_weight_lbs` is at least `measured_tare_lbs` — either failure is rejected with `ERR_TARE_MISMATCH`. If the intake weight itself was misrecorded, a reweigh moves the ticket from `WEIGHED` back to `OPEN` with a new `pre_weight_lbs` and resets `measured_tare_lbs` to null; this weigh–reweigh loop may repeat as often as needed.

Filling is the regulated act, and its guards run in the evaluation order of §2.7: the ticket must be `WEIGHED` (else `ERR_INVALID_STATE`); the cylinder must not be `CONDEMNED` (else `ERR_CYLINDER_CONDEMNED`); it must be `CERTIFIED` — a `RECERT_DUE` bottle is rejected with `ERR_CYLINDER_NOT_CERTIFIED`; and it must not be `QUARANTINED` (else `ERR_CYLINDER_QUARANTINED`). The clerk then records `post_weight_lbs`, and the dispensed quantity `propane_lbs` is computed as `post_weight_lbs` minus `pre_weight_lbs`, rounded half-up to two decimal places. The overfill guard is inclusive at the ceiling: `propane_lbs` equal to `max_fill_lbs` is permitted, and any excess, however small, is rejected with `ERR_OVERFILL_RISK`. On a successful fill the tier rates are pinned from the site's current policy onto the ticket as `tier1_cents_per_lb`, `tier2_cents_per_lb`, and `tier1_max_lbs`, and the charge is computed per §2.5's per-tier doctrine: the tier-one quantity is the smaller of `propane_lbs` and `tier1_max_lbs`; the tier-two quantity is whatever remains of `propane_lbs`; each tier's pounds are multiplied by that tier's per-pound rate and rounded half-up to whole cents individually; and `propane_charge_cents` is the sum of the two rounded tier amounts. The `hazmat_fee_cents` on the ticket is zero when the site's `promo_waives_hazmat` is true and the site's flat `hazmat_fee_cents` otherwise, and the ticket's `total_cents` is `propane_charge_cents` plus `hazmat_fee_cents`. The ticket lands in `FILLED`.

Closing takes the money. The clerk tenders `payment_cash_cents`, which must equal or exceed `total_cents` (else `ERR_INSUFFICIENT_PAYMENT`); the cylinder's `fill_status` becomes `FULL`; `business_date`, `sale_seq`, and `change_due_cents` are stamped exactly as at the exchange counter; the ticket lands in `CLOSED`; and the site's open reconciliation session for the current date, if one exists, recomputes `expected_cash_cents` to include the ticket's `total_cents` as a cash addition. Voiding exists for the early stages only: an `OPEN` or `WEIGHED` ticket may be voided to `VOIDED`, but a `FILLED` ticket cannot be voided — the propane is already in the customer's bottle — and must be closed instead. Refill tickets may be listed filtered by `site_id`, `cylinder_id`, or `status`.

### 3.5. Leak Response, Cage Quarantine, and Re-Inspection

Any clerk can raise the alarm. A `SiteClerk` files a leak report with the `site_id`, a `severity` of `MINOR` or `MAJOR`, an optional `quarantine_cage` recommendation (defaulting to false), an optional `cylinder_id` when a specific bottle is suspect, and an optional free-text `note`; the reporter's `X-User-ID` is recorded as `reporter_clerk_id`. A site may carry at most one open leak — that is, one report in `REPORTED` or `CONFIRMED` status — and a second filing is rejected with `ERR_LEAK_ALREADY_OPEN`. The report stands in `REPORTED`.

A `ComplianceOfficer` then adjudicates. Marking the report a false alarm moves it to `FALSE_ALARM` and records the supplied `reason` text into `false_alarm_reason`; nothing else changes. Confirming the report is the heavy path. The officer's identity and the current date are stamped as `confirmed_by` and `confirmed_on`. When the confirmed leak is `MAJOR`, or when `quarantine_cage` was recommended, a cage-wide quarantine cascade fires: every fleet cylinder at the site in `FULL` or `EMPTY` fill status becomes `QUARANTINED`; because cylinder fill states changed, the site's `full_on_hand`, `empty_on_hand`, and `quarantined_on_hand` recompute; and because `full_on_hand` recomputed, `restock_alert` flips on if the count now sits at or below `reorder_floor_full`. Independently of severity, a confirmed quarantining leak recomputes the site's `sales_posture` to `SALES_BLOCKED`, and the moment the posture blocks, every `DRAFT` exchange order at the site is auto-voided with `void_reason` `SAFETY` and every `OPEN` or `WEIGHED` refill ticket at the site is auto-voided; those drafts carried no captured cash, so the day's reconciliation expectation is unchanged in value but is recomputed. A `MINOR` confirmed leak without a quarantine recommendation engages no cage quarantine and does not block sales.

Officers may also act on individual bottles outside any report. Quarantining a cylinder moves it from `FULL` or `EMPTY` to `QUARANTINED` — an optional `note` may be attached — and releasing a quarantined cylinder returns it to service as `EMPTY`, but only when its `cert_status` is `CERTIFIED`; releasing a `RECERT_DUE` cylinder is rejected with `ERR_CYLINDER_NOT_CERTIFIED`. Both actions recompute the site's counts and `restock_alert`.

Resolution closes the loop. Resolving requires the report to be `CONFIRMED` (else `ERR_INVALID_STATE`), and for quarantining leaks it requires re-inspection evidence: at least one certification record with `outcome` `PASS` in `RECORDED` status, `performed_on` on or after the report's `confirmed_on`, for a fleet cylinder whose `current_site_id` is the affected site — without that evidence the resolution is rejected with `ERR_REINSPECTION_REQUIRED`. Segregation of duties applies at the close: the resolving officer must not be the clerk who filed the report, else `ERR_SEGREGATION_OF_DUTIES`. A successful resolution stamps `resolved_by` and the supplied `resolution_note`, moves the report to `RESOLVED`, and recomputes the site's `sales_posture` — which returns to `SALES_OPEN` when no other confirmed quarantining leak remains. Leak reports may be listed filtered by `site_id`, `cylinder_id`, or `status`.

### 3.6. Restock Logistics: Forecasting, Dispatch, Delivery, and Verification

Restocking begins with a plan. A `PlatformAdmin` creates a restock run naming exactly one destination `site_id`, an assigned `driver_id`, a `planned_date`, and the OCC field `expected_site_version` (§2.6); a stale site view rejects the create with `ERR_STALE_VERSION`, and a successful create advances the site's `version` by one. Creation also supersedes: any existing `DRAFT` run for the same site is auto-cancelled, so a site carries at most one draft plan at a time. Two planned quantities are computed and frozen at creation. `planned_empty_pickup_count` is simply the site's `empty_on_hand` snapshot. `planned_full_count` is the forecast-driven suggestion: count the site's completed exchanges whose `business_date` falls in the trailing fourteen-day half-open window — beginning fourteen days before the current date and ending the day before it — and divide by fourteen to obtain the average daily swap rate, kept as an exact rational; multiply that average by the number of whole days from the current date to `planned_date` (floored at zero when the run is planned for today) and round up to a whole cylinder for the forecast demand; subtract the forecast from the site's current `full_on_hand` to project stock at arrival, a projection that may go negative; and finally set the suggestion to the smaller of the cage's free space — `cage_capacity_cylinders` minus `full_on_hand` — and the larger of zero and `par_level_full` minus the projection. The run stands in `DRAFT`, with `assigned_cylinder_count` at zero.

Dispatch is where DOT compliance bites, and its gates run within the §2.7 order: the run must be `DRAFT` (else `ERR_INVALID_STATE`); the site must be `ACTIVE` (else `ERR_SITE_NOT_ACTIVE`); the driver must be `ACTIVE` — a suspended driver rejects with `ERR_INVALID_STATE`; the `planned_date` must be on or before the driver's `dot_medical_expires_on` (else `ERR_DRIVER_CERT_EXPIRED`); the driver must have no other run in `DISPATCHED` or `IN_PROGRESS` on the same `planned_date` (else `ERR_DRIVER_ROUTE_CONFLICT`); and the route must be non-empty — `planned_full_count` plus `planned_empty_pickup_count` greater than zero, else `ERR_EMPTY_ROUTE`. The payload check uses fixed cage weights: each planned full cylinder weighs 37 pounds and each planned empty 17 pounds, and the planned payload — fulls times 37 plus empties times 17 — must not exceed the driver's `vehicle_max_payload_lbs`; equality is permitted, and any excess rejects with `ERR_DOT_PAYLOAD_EXCEEDED`. Finally the depot must be able to fill the order: the depot pool — fleet-owned, `CERTIFIED`, `FULL` cylinders with `current_site_id` null and not in transit — must hold at least `planned_full_count` cylinders, else `ERR_DEPOT_STOCK_LOW`. On success the depot selector assigns the planned quantity using the same oldest-certified ranking as the sales selector (`certified_on` ascending, ties by `created_at` ascending), stamps each assigned cylinder's `in_transit_run_id` with the run, and the run's `assigned_cylinder_count` recomputes. The run is now `DISPATCHED`.

From the road, the assigned driver — and only that driver, verified by comparing `X-User-ID` to the run's `driver_id` (else `ERR_FORBIDDEN`) — marks arrival, which requires the current logical date to equal the `planned_date` (else `ERR_INVALID_STATE`) and moves the run from `DISPATCHED` to `IN_PROGRESS`. Completing the run is again the assigned driver's act, recording the actual `delivered_full_count` and `picked_up_empty_count`. Both counts are bounded: delivered fulls must lie between zero and `assigned_cylinder_count`, and picked-up empties between zero and the site's `empty_on_hand`; a negative count or an over-count is rejected with `ERR_VALIDATION`. Completion then moves the metal: delivered cylinders take `current_site_id` of the run's site with `in_transit_run_id` cleared, raising the site's `full_on_hand`; assigned cylinders that were not delivered return to the depot with `in_transit_run_id` cleared; picked-up empties leave the site into transit, carrying the run's id in `in_transit_run_id` and a null `current_site_id`, dropping the site's `empty_on_hand`. The run's `variance_full_count` is computed as `delivered_full_count` minus `planned_full_count`, the site's counts and `restock_alert` recompute, and the run lands in `COMPLETED`.

Verification closes the route under segregation of duties: a `PlatformAdmin` or `SiteClerk` whose `X-User-ID` differs from the run's `driver_id` — an equal identity rejects with `ERR_SEGREGATION_OF_DUTIES` — verifies a `COMPLETED` run, stamping `verified_by`; at that moment the picked-up empties are accepted at the depot and their `in_transit_run_id` is cleared, and the run reaches its terminal `VERIFIED` state. Cancellation is available from either `DRAFT` or `DISPATCHED`; cancelling a dispatched run releases every assigned cylinder back to the depot by clearing its `in_transit_run_id`, and the run ends `CANCELLED`. Runs may be listed filtered by `site_id`, `driver_id`, `status`, or `planned_date`.

Drivers themselves are registered with a `name`, a `license_number` unique across drivers (duplicates rejected with `ERR_VALIDATION`), the `dot_medical_expires_on` date of their DOT medical card, and their vehicle's `vehicle_max_payload_lbs` (greater than zero). A `PlatformAdmin` may later patch the medical expiry, the payload limit, or the driver `status`, which cycles between `ACTIVE` and `SUSPENDED`. Technicians are registered with a `name` and a `cert_level` of `VISUAL_ONLY` or `FULL`, begin `ACTIVE`, and may likewise be patched between `ACTIVE` and `SUSPENDED` or to a new `cert_level`.

### 3.7. Commission Settlement and Host-Site Disputes

Host sites are paid on what they sell. A `PlatformAdmin` opens a commission statement for a site with a closed `period_start`–`period_end` interval: both bounds inclusive, `period_end` on or after `period_start`, and the span no longer than 62 days; malformed periods are rejected with `ERR_VALIDATION`. Creation snapshots the site's `commission_basis` into the statement's `basis_used` — the variant is frozen even if the site's basis later changes — and the statement stands in `DRAFT`.

Finalization is where the settlement math runs, and it demands a clean ledger. The statement must be `DRAFT` (else `ERR_INVALID_STATE`); the `period_end` must lie strictly before the current logical date (else `ERR_PERIOD_NOT_CLOSED`); and every calendar date in the closed interval must have at least one reconciliation session for the site in `BALANCED` or `RESOLVED` — any unreconciled date rejects the finalize with `ERR_RECONCILIATION_UNRESOLVED`. The settlement then proceeds in pinned order. The input set is every exchange order in `COMPLETED` or `REFUNDED` status and every refill ticket in `CLOSED` status whose `business_date` falls inside the period, ordered by `sale_seq` ascending; drafts, voided orders, and non-closed tickets are excluded. `gross_sales_cents` is the sum of `total_cents` across that set. `refunds_cents` is the sum of `total_cents` over the orders in the set that are `REFUNDED` with a `refunded_on` inside the period. The commissioned base depends on the frozen variant: under `GROSS` the refunded-in-period sales remain in the commissioned set and `base_cents` equals `gross_sales_cents`; under `NET` the refunded-in-period sales are excluded and `base_cents` is `gross_sales_cents` minus `refunds_cents`, so identical raw sales yield a smaller base under `NET`.

Commission itself is tiered and marginal, walked sale by sale in `sale_seq` order with a running cumulative over the commissioned set. For each sale, the below-threshold portion is the larger of zero and the smaller of (running cumulative plus the sale's `total_cents`) and the site's `commission_tier_threshold_cents`, minus the running cumulative; the above-threshold portion is the remainder of the sale's `total_cents`. The sale's commission is the below-threshold portion multiplied by `commission_rate_bps`, plus the above-threshold portion multiplied by the sum of `commission_rate_bps` and `commission_tier2_bonus_bps`, each rate divided by ten thousand, and the whole sale figure rounded half-up to whole cents before being added into `commission_cents`; the running cumulative then advances by the sale's `total_cents`. Leak history then bites: `leak_count` is the number of leak reports for the site in `CONFIRMED` or `RESOLVED` status whose `confirmed_on` falls inside the period, and `leak_deduction_cents` is that count times 25,000 cents — a $250.00 penalty per confirmed leak. The payable figure `net_payable_cents` is `commission_cents` minus `leak_deduction_cents`, floored at zero. Finalization stamps `finalized_on` and moves the statement to `FINALIZED`.

The host site gets its say through the dispute loop. A `HostSiteManager` — whose `X-User-ID` must equal the statement's `site_id`, else `ERR_FORBIDDEN` — disputes a `FINALIZED` statement by supplying a `note`, which is stored as `dispute_note` while the statement moves to `DISPUTED`. An administrator may then finalize the disputed statement again: the same closed-period and full-reconciliation preconditions apply, the entire settlement is recomputed from current data, and `finalized_on` is refreshed; this finalize–dispute–refinalize loop may repeat indefinitely. Once both sides are satisfied, paying a `FINALIZED` statement stamps `paid_on` and moves it to the terminal `PAID` state. Statements may be listed filtered by `site_id` or `status`, with a host-site manager's listing scoped to their own site.

### 3.8. Daily Reconciliation: Counts, Variances, and Escalation

Each site's trading day closes against the book. A `SiteClerk` opens a reconciliation session for a `site_id` and a `business_date`, optionally carrying an `idempotency_key` per §2.9; the pair of site and business date is unique, and a duplicate open is rejected with `ERR_SESSION_EXISTS`. The shift clerk's `X-User-ID` is recorded as `clerk_id`, and the site's `recon_basis` is copied into the session's `basis` at creation. The opening baseline depends on that variant: under `BOOK` the `opening_baseline_cents` is the site's declared `opening_float_cents`; under `PHYSICAL` it is the `counted_cash_cents` of the site's most recent prior session — the one with the largest `business_date` strictly before the session's date — in `BALANCED` or `RESOLVED` status, falling back to `opening_float_cents` when no such prior session exists, so a physical-baseline site carries yesterday's counted over- or short-position into today while a book-baseline site does not. The session also snapshots `expected_cash_cents`, `expected_full_cylinders`, and `expected_empty_cylinders`. The expected cash is the opening baseline plus the day's cash events — exchange completions add their `total_cents`, refill closes add their `total_cents`, and refunds subtract their `total_cents` — snapshotted at creation and recomputed whenever a count or recount is submitted, and kept current as cash events land on an open session's `business_date` per §3.3 and §3.4. The cylinder expectations are the site's `full_on_hand` and `empty_on_hand` at session creation.

Counting is the clerk's physical close. The clerk submits `counted_cash_cents`, `counted_full_cylinders`, and `counted_empty_cylinders`; the session recomputes expectations and stores three variances — `cash_variance_cents` as counted cash minus expected cash, `full_variance` as counted fulls minus expected fulls, and `empty_variance` as counted empties minus expected empties. The balance rule is strict: when the absolute cash variance is under 500 cents and both cylinder variances are exactly zero, the session transitions from `OPEN` to `BALANCED`; otherwise it transitions to `VARIANCE_FLAGGED`. The cash threshold is inclusive on the flag side — an absolute variance of exactly 500 cents flags the session.

A flagged session has three roads. A recount returns it from `VARIANCE_FLAGGED` to `OPEN`, resetting `counted_cash_cents`, `counted_full_cylinders`, `counted_empty_cylinders`, and all three variance fields to null for a fresh count; this flag–recount loop may repeat as often as needed. Alternatively a `PlatformAdmin` or `ComplianceOfficer` escalates the flagged session — optionally attaching a `note` — stamping `escalated_by` and moving it to `ESCALATED`. Finally, a `PlatformAdmin` or `ComplianceOfficer` resolves an `ESCALATED` session by supplying a `resolution_note`; segregation of duties forbids the resolver from being the shift clerk whose `clerk_id` opened the session, rejecting that attempt with `ERR_SEGREGATION_OF_DUTIES`. Resolution stamps `resolved_by` alongside the note and lands the session in `RESOLVED`. Both `BALANCED` and `RESOLVED` are terminal. Sessions may be listed filtered by `site_id`, `business_date`, or `status` — and per §3.3, a session's state gates same-day refunds, while per §3.7 its terminal states gate commission finalization.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions and configuration patches — return a `200 OK` status code. Readers must refer back to §3 narratives for the complete request and response semantics of each operation; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps lapsed certifications to `RECERT_DUE` | PlatformAdmin |
| POST | `/sites` | Create a host site | PlatformAdmin |
| GET | `/sites` | List sites with pagination | PlatformAdmin, ComplianceOfficer |
| GET | `/sites/{siteId}` | Read a site including computed cage counts, sales posture, and restock alert | PlatformAdmin, SiteClerk, HostSiteManager, Driver, Technician, ComplianceOfficer |
| PATCH | `/sites/{siteId}` | Update site configuration or status; OCC-guarded | PlatformAdmin |
| POST | `/pricing-policies` | Create a pricing policy; optional supersede clips the current window; OCC-guarded | PlatformAdmin |
| GET | `/pricing-policies` | List pricing policies, filterable by site | PlatformAdmin, HostSiteManager |
| GET | `/pricing-policies/{policyId}` | Read a pricing policy | PlatformAdmin, HostSiteManager |
| POST | `/drivers` | Register a driver | PlatformAdmin |
| GET | `/drivers/{driverId}` | Read a driver | PlatformAdmin, Driver |
| PATCH | `/drivers/{driverId}` | Update driver status or DOT fields | PlatformAdmin |
| POST | `/technicians` | Register a technician | PlatformAdmin |
| GET | `/technicians/{technicianId}` | Read a technician | PlatformAdmin, Technician |
| PATCH | `/technicians/{technicianId}` | Update technician status or cert level | PlatformAdmin |
| POST | `/cylinders` | Register a cylinder; fleet registration is admin-only | PlatformAdmin, SiteClerk |
| GET | `/cylinders` | List cylinders with filters | PlatformAdmin, SiteClerk, Technician, ComplianceOfficer |
| GET | `/cylinders/{cylinderId}` | Read a cylinder | PlatformAdmin, SiteClerk, Technician, ComplianceOfficer, Driver |
| POST | `/cylinders/{cylinderId}/quarantine` | Quarantine a cylinder | ComplianceOfficer |
| POST | `/cylinders/{cylinderId}/release-quarantine` | Release a quarantined, certified cylinder to `EMPTY` | ComplianceOfficer |
| POST | `/exchange-orders` | Create a swap order with prices pinned from the current policy; idempotent per clerk | SiteClerk |
| GET | `/exchange-orders` | List exchange orders with filters | SiteClerk, PlatformAdmin, HostSiteManager |
| GET | `/exchange-orders/{orderId}` | Read an exchange order | SiteClerk, PlatformAdmin, HostSiteManager |
| POST | `/exchange-orders/{orderId}/complete` | Complete a swap: selector issues the oldest-certified full fleet cylinder; cash captured | SiteClerk |
| POST | `/exchange-orders/{orderId}/void` | Void a `DRAFT` order; no cash was captured | SiteClerk |
| POST | `/exchange-orders/{orderId}/refund` | Refund a `COMPLETED` order same-day; issued cylinder returns quarantined | SiteClerk |
| POST | `/refill-tickets` | Open a refill ticket for a customer cylinder | SiteClerk |
| GET | `/refill-tickets` | List refill tickets with filters | SiteClerk, PlatformAdmin |
| GET | `/refill-tickets/{ticketId}` | Read a refill ticket | SiteClerk, PlatformAdmin |
| POST | `/refill-tickets/{ticketId}/weigh` | Record the empty-scale reading and verify tare tolerance | SiteClerk |
| POST | `/refill-tickets/{ticketId}/reweigh` | Return a weighed ticket to open with a new intake weight | SiteClerk |
| POST | `/refill-tickets/{ticketId}/fill` | Record the post-fill weight; enforces certification and the fill limit; computes the charge | SiteClerk |
| POST | `/refill-tickets/{ticketId}/close` | Take payment and close a filled ticket | SiteClerk |
| POST | `/refill-tickets/{ticketId}/void` | Void an open or weighed ticket | SiteClerk |
| POST | `/certification-records` | Record a certification outcome; `PASS` is immediate, `CONDEMN` awaits a second signature | Technician |
| GET | `/certification-records` | List certification records with filters | Technician, PlatformAdmin, ComplianceOfficer |
| GET | `/certification-records/{recordId}` | Read a certification record | Technician, PlatformAdmin, ComplianceOfficer |
| POST | `/certification-records/{recordId}/confirm` | Second-signature confirm of a pending condemn by a different `FULL` technician | Technician |
| POST | `/certification-records/{recordId}/reject` | Second-signature reject of a pending condemn by a different `FULL` technician | Technician |
| POST | `/leak-reports` | Report a leak at a site; at most one open leak per site | SiteClerk |
| GET | `/leak-reports` | List leak reports with filters | SiteClerk, PlatformAdmin, ComplianceOfficer, HostSiteManager |
| GET | `/leak-reports/{reportId}` | Read a leak report | SiteClerk, PlatformAdmin, ComplianceOfficer, HostSiteManager |
| POST | `/leak-reports/{reportId}/confirm` | Confirm a leak; `MAJOR` or cage-quarantine recommendation engages the quarantine cascade | ComplianceOfficer |
| POST | `/leak-reports/{reportId}/resolve` | Resolve a confirmed leak; quarantining leaks require re-inspection evidence | ComplianceOfficer |
| POST | `/leak-reports/{reportId}/false-alarm` | Mark a reported leak as a false alarm | ComplianceOfficer |
| POST | `/restock-runs` | Create a restock run for one site; supersedes any existing draft; OCC-guarded | PlatformAdmin |
| GET | `/restock-runs` | List restock runs with filters | PlatformAdmin, Driver, SiteClerk |
| GET | `/restock-runs/{runId}` | Read a restock run | PlatformAdmin, Driver, SiteClerk |
| POST | `/restock-runs/{runId}/dispatch` | Dispatch a draft run: DOT checks, depot selector assigns cylinders | PlatformAdmin |
| POST | `/restock-runs/{runId}/arrive` | Assigned driver marks arrival on the planned date | Driver |
| POST | `/restock-runs/{runId}/complete` | Assigned driver records actual delivered and picked-up counts | Driver |
| POST | `/restock-runs/{runId}/verify` | Verify a completed run; verifier differs from driver | PlatformAdmin, SiteClerk |
| POST | `/restock-runs/{runId}/cancel` | Cancel a draft or dispatched run; assigned cylinders return to depot | PlatformAdmin |
| POST | `/commission-statements` | Create a commission statement; basis snapshot from the site | PlatformAdmin |
| GET | `/commission-statements` | List commission statements; host-site managers see only their own site | PlatformAdmin, HostSiteManager |
| GET | `/commission-statements/{statementId}` | Read a commission statement | PlatformAdmin, HostSiteManager |
| POST | `/commission-statements/{statementId}/finalize` | Finalize: computes the settlement; requires a closed, fully reconciled period | PlatformAdmin |
| POST | `/commission-statements/{statementId}/dispute` | Host site disputes a finalized statement (own site only) | HostSiteManager |
| POST | `/commission-statements/{statementId}/pay` | Mark a finalized statement paid | PlatformAdmin |
| POST | `/reconciliation-sessions` | Open a reconciliation session for a site and business date; idempotent per clerk | SiteClerk |
| GET | `/reconciliation-sessions` | List reconciliation sessions with filters | SiteClerk, PlatformAdmin, ComplianceOfficer |
| GET | `/reconciliation-sessions/{sessionId}` | Read a reconciliation session | SiteClerk, PlatformAdmin, ComplianceOfficer |
| POST | `/reconciliation-sessions/{sessionId}/count` | Submit physical counts; transitions to balanced or flagged | SiteClerk |
| POST | `/reconciliation-sessions/{sessionId}/recount` | Reset a flagged session back to open for a fresh count | SiteClerk |
| POST | `/reconciliation-sessions/{sessionId}/escalate` | Escalate a flagged session | PlatformAdmin, ComplianceOfficer |
| POST | `/reconciliation-sessions/{sessionId}/resolve` | Resolve an escalated session; resolver differs from shift clerk | PlatformAdmin, ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3; this catalogue is a routing summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SITE_NOT_ACTIVE` | 409 Conflict |
| `ERR_SITE_NOT_EMPTY` | 409 Conflict |
| `ERR_SALES_BLOCKED` | 409 Conflict |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |
| `ERR_NO_STOCK` | 409 Conflict |
| `ERR_DEPOT_STOCK_LOW` | 409 Conflict |
| `ERR_CYLINDER_CONDEMNED` | 409 Conflict |
| `ERR_CYLINDER_NOT_CERTIFIED` | 409 Conflict |
| `ERR_CYLINDER_QUARANTINED` | 409 Conflict |
| `ERR_NOT_REFILLABLE` | 409 Conflict |
| `ERR_TARE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OVERFILL_RISK` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_PAYMENT` | 402 Payment Required |
| `ERR_DOT_PAYLOAD_EXCEEDED` | 409 Conflict |
| `ERR_DRIVER_CERT_EXPIRED` | 409 Conflict |
| `ERR_DRIVER_ROUTE_CONFLICT` | 409 Conflict |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_POLICY_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_EMPTY_ROUTE` | 422 Unprocessable Entity |
| `ERR_SESSION_EXISTS` | 409 Conflict |
| `ERR_RECONCILIATION_UNRESOLVED` | 409 Conflict |
| `ERR_PERIOD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_REFUND_WINDOW_CLOSED` | 409 Conflict |
| `ERR_LEAK_ALREADY_OPEN` | 409 Conflict |
| `ERR_REINSPECTION_REQUIRED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |
