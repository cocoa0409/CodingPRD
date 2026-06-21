# iBuyer Home Offer API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for an instant-offer home-buying platform of the kind that lets a homeowner request a cash offer on their house, accept it, and close on a schedule of their choosing — without the uncertainty of a traditional listing. The platform's economic engine is an automated valuation model (AVM) that prices a property from comparable sales data, layers a transparent service fee and a small seller concession on top, and produces an immediate, expiring offer. Where a conventional sale leaves a seller guessing at their net proceeds until late in escrow, this system commits to a number up front and then reconciles it against the realities discovered during a home assessment and inspection.

The product's central challenge is that a property is valued and priced **twice**. At the moment an offer is issued, the platform computes a *provisional* payout using only the AVM snapshot — no assessment has happened, no repairs are known, and no lease-back has been chosen. Later, once the seller has accepted, the home has been assessed, repair line items have been catalogued, a close date and any late-checkout lease-back have been selected, and a possible inspection re-trade has adjusted the valuation, the platform computes the *final* payout from the same conceptual inputs but with real numbers. The two figures legitimately diverge, and much of this specification is concerned with making both computations precise and reproducible. A parallel pair of figures governs the back end of the business: when the platform relists an acquired home, it projects a resale spread at listing and reconciles a net spread at sale.

A handful of operator personas drive the workflow. A homeowner registers and makes accept/decline/close decisions; a pricing operator issues offers and negotiates inspection re-trades; and a back-office operator runs assessments, inspections, closings, and resale. Because offer expiration and closing windows are time-sensitive, the system runs on a controllable logical clock rather than wall-clock time, so that every temporal rule is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request (with the single exception of the logical-clock control endpoint described in §2.7) must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role named in `X-User-Role` is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly three roles, spelled precisely as follows: `Seller`, `PricingAnalyst`, and `OperationsAdmin`.

The `Seller` role is **entity-backed**. When `X-User-Role` is `Seller`, the value of `X-User-ID` is the `id` of the acting `Seller` record. Ownership checks on any resource that ultimately references a `Seller` compare against this value: a property's `seller_id` is the homeowner that owns it, and ownership of an offer or transaction flows through the property they reference. Concretely, whenever a `Seller` acts on a property, an offer, or a transaction, the underlying property's `seller_id` must equal `X-User-ID`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The `PricingAnalyst` and `OperationsAdmin` roles are both **opaque** operator identifiers. When `X-User-Role` is `PricingAnalyst` or `OperationsAdmin`, the value of `X-User-ID` is an operator identifier that is not tied to any persisted entity; the server may accept and record it for audit purposes but never compares it to any entity's `id` for ownership. These two roles are not subject to the ownership check; their authority comes entirely from the role-permission matrix in §4.

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

List endpoints accept two pagination parameters, `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a requested value above the maximum is not honored beyond 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Every list is returned in ascending order of `created_at`, oldest first. For list responses, the `meta` object carries the effective `limit` and `offset` alongside `total_count` (the total number of records matching the query before pagination) and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties

Every resource is assigned a server-minted `id`, which is a UUID carrying no type prefix. All resources additionally record a `created_at` timestamp. Most resources also maintain an `updated_at` timestamp and an integer `version`: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that begins at 1 when the resource is created and increments by exactly 1 on every mutation that changes the resource, with `updated_at` refreshed to the logical-clock instant of that mutation. In this system, the `Seller`, `Property`, `Offer`, `Assessment`, `RepairLineItem`, `Transaction`, and `Resale` resources all carry the full set — `id`, `created_at`, `updated_at`, and `version`.

### 2.5. Monetary Precision and Rounding

All monetary and valuation amounts are carried to 2 decimal places and rounded using the round-half-up convention (a value exactly at the half-cent rounds away from zero, upward). Wherever a calculation in §3 specifies an intermediate rounding step, that intermediate result is itself rounded to 2 decimal places with round-half-up before it participates in any further arithmetic. The order of rounding relative to summation and multiplication is significant and is stated explicitly for each affected computation; implementers must not reorder these steps, because rounding-then-summing and summing-then-rounding produce different cents.

### 2.6. Derived-Field Reconciliation and Cascades

Several fields are *derived*: they are not supplied by the client but computed from other state, and they must be kept consistent within the same request that changes their inputs. When an operation alters a value that feeds a derived field, every dependent derived field is recomputed immediately, before the response is returned. The most consequential cascade is the inspection re-trade: lowering a property's effective valuation flows through to the effective service fee, the lease-back daily rate and total, and the final net proceeds, all of which are recomputed in the same request. When a re-trade is later unwound by a cancellation, the revised valuation is reverted as well. Whenever such a recomputation mutates an entity, that entity's `version` increments and its `updated_at` advances per §2.4. Parent/child state propagation — for example a property's lifecycle status moving in lock-step with its bound offer and transaction — follows the same immediate-consistency principle and is detailed in §3.

### 2.7. Nested-Resource Path Validation and the Logical Clock

Endpoints whose URLs nest one resource under another (for example, the offers issued for a particular property, or the repair line items of a particular assessment) validate their path segments left to right. The outer resource is resolved first; if it does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404) before any inner segment or body reference is considered. The same `ERR_NOT_FOUND` governs foreign-key references supplied in a request body that do not resolve to an existing record.

Across every create and update operation, the request body must carry all of that operation's required fields, each of the correct type and — where a field is an enumeration or a bounded number — within its permitted domain. A missing required field, a value of the wrong type, or a value outside its declared enum or numeric range is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Time in this system is governed by a **logical clock** rather than the host wall clock. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly advanced it never falls back to real time. An administrative capability advances the clock to a supplied instant; this is the only endpoint exempt from the authentication headers of §2.1. Every temporal rule in this document — offer expiry, the close-date window, the inspection-window opening — is evaluated against this logical clock.

### 2.8. Optimistic Concurrency on Property Re-Issue

Issuing the very first offer for a property does not require a version token. Re-issuing an offer for a property that is already under offer, however, is guarded by optimistic concurrency control on the property. A re-issue request to the property's offer-creation operation must carry `expected_property_version` holding the client's last observed `Property.version`. If that value does not equal the property's current `version` — because some other writer has advanced the property since the client last read it — the re-issue is rejected with `ERR_STALE_VERSION` (HTTP 412), so that the client never supersedes an offer it has not actually observed. A re-issue is a legitimate product action that succeeds from a correctly observed state; the version check, not a state precondition, is what stops a stale second writer. Only this re-issue operation takes `expected_property_version`; no other endpoint accepts a version token.

## 3. Business Logic & Workflows

### 3.1. Registering Sellers and Properties

A homeowner enters the system as a `Seller`. Registration captures the seller's login `email`, which must be unique across all sellers, the seller's legal `full_name`, and an optional `payout_method` indicating where net proceeds are wired. The `payout_method` accepts either `ACH` or `WIRE` and defaults to `ACH` when omitted. A freshly registered seller carries no lifecycle status; it is simply a party of record.

Once registered, a seller's home is entered as a `Property`. Property registration is performed by a pricing or back-office operator and requires the owning homeowner's identifier in `seller_id`, the `address_line`, a five-digit `zip_code` used to select the comparable-sales set, a `bedrooms` count that must be zero or greater, a `living_area_sqft` figure for heated living area that must be at least 1, and the `comp_median_value` — the median sale price of the comparable set, in dollars, which must be zero or greater. The registrant may also supply `market_trend_pct`, a signed ZIP-level market trend applied to the comparables (for instance, a value of 0.02 represents a two-percent uplift). The trend defaults to 0.0 and must lie between -0.50 and 0.50 inclusive.

At registration the platform immediately computes the property's automated valuation, `avm_value`, by taking `comp_median_value`, multiplying it by one plus `market_trend_pct`, and rounding the result half-up to two decimal places. A newly registered property opens in `VALUED` status. Its `revised_avm_value` (the valuation after an accepted re-trade) starts null, its `condition_score` starts null until a home assessment writes it, and its `active_offer_id` (a denormalized pointer to the single non-terminal offer bound to the property) starts null. The property's `status` traverses `VALUED → UNDER_OFFER → IN_TRANSACTION → SOLD`, with `WITHDRAWN` as an alternate terminal outcome.

### 3.2. Issuing and Re-Issuing Offers

A `PricingAnalyst` issues an instant `Offer` against a property. The first issuance is permitted only when the property is in `VALUED` status with no active offer bound, and only when the property's `avm_value` is at least the minimum offerable value of 50,000 dollars; a property valued below that floor is rejected with `ERR_PROPERTY_BELOW_MIN_VALUE`. On a successful first issuance the property transitions `VALUED → UNDER_OFFER`, a new offer is created in `ISSUED` status, and the property's `active_offer_id` is set to that new offer's `id`.

At issuance the offer captures the property's valuation into `avm_value_snapshot` and prices itself entirely off that snapshot. The analyst may supply `service_fee_pct`, the platform's service-fee fraction of the snapshot, which defaults to 0.05 and must lie between 0 and 0.15 inclusive. The `service_fee` is the snapshot multiplied by `service_fee_pct`, rounded half-up to two decimal places. The provisional seller concession, `estimated_concession`, is the snapshot multiplied by one percent, rounded half-up to two decimal places. The offer's provisional payout, `preliminary_net_proceeds`, is then the snapshot minus the `service_fee` minus the `estimated_concession`, rounded half-up to two decimal places; at issuance there is no assessment, so any repair credit is treated as zero and no lease-back is contemplated. The offer records its `issued_at` as the current logical-clock instant and sets `expires_at` to five days after `issued_at`. An offer's `status` is one of `ISSUED`, `ACCEPTED`, `DECLINED`, `EXPIRED`, or `SUPERSEDED`.

Whether an offer-POST is treated as a first issuance or as a re-issue is decided solely by whether the property currently has an active offer bound: when `active_offer_id` is null the request follows the first-issuance rules above, and when `active_offer_id` is non-null the request is a re-issue and is routed through the re-issuability check below — regardless of the property's `status`. In particular, after an offer is accepted the property's `active_offer_id` still points at that now-`ACCEPTED` offer even though the property has advanced to `IN_TRANSACTION`, so a further offer-POST is treated as a re-issue and reaches the re-issuability check (yielding `ERR_OFFER_NOT_REISSUABLE`) rather than the first-issuance branch.

Re-issuing an offer for a property already `UNDER_OFFER` keeps the property in `UNDER_OFFER` but replaces the offer. A re-issue is permitted only when the property's currently active offer is in one of `ISSUED`, `EXPIRED`, or `DECLINED` status; if the active offer is `ACCEPTED` or `SUPERSEDED` it cannot be superseded again and the request is rejected with `ERR_OFFER_NOT_REISSUABLE`. As established in §2.8, a re-issue must also carry `expected_property_version` equal to the property's current `version`, failing with `ERR_STALE_VERSION` otherwise. When a re-issue succeeds, the prior active offer moves to `SUPERSEDED` (with no payout effect — a superseded offer simply ceases to be acceptable), a new offer is created in `ISSUED`, the property's `active_offer_id` is repointed to the new offer, and the property's `version` increments by 1.

### 3.3. Offer Expiry, Acceptance, Decline, and Withdrawal

An offer is alive only while the logical clock is before its `expires_at`. Expiry is observed lazily: the system does not sweep offers in the background but evaluates the clock at the moment a seller acts. When the owning `Seller` accepts an offer, the offer must still be in `ISSUED` status and the clock must be strictly before `expires_at`; an accept attempted at or after `expires_at` is rejected with `ERR_OFFER_EXPIRED`. The accepting seller must own the underlying property, and the offer being accepted must be the property's current `active_offer_id` while the property is `UNDER_OFFER`. A successful acceptance moves the offer `ISSUED → ACCEPTED` and the property `UNDER_OFFER → IN_TRANSACTION`, and it spawns two children: a home `Assessment` in `DRAFT` status bound to the accepted offer, and a `Transaction` in `PENDING_ASSESSMENT` status.

A seller may instead decline an offer. A decline against an offer whose `expires_at` has already passed reports the expiry: the offer moves `ISSUED → EXPIRED`, and an explicit decline of a still-valid offer is likewise a terminal disposition of that offer. In either case, if the declined or expired offer was the property's active offer, the property's `active_offer_id` is cleared to null and the property returns to `VALUED`.

Separately, the seller may withdraw the whole property from offer while it is `UNDER_OFFER`. Withdrawal is blocked once a transaction has advanced past `PENDING_ASSESSMENT`; an attempt to withdraw while such a transaction is in flight — that is, while a transaction for the property is in `SCHEDULED` or `INSPECTION` — is rejected with `ERR_PROPERTY_LOCKED`. This in-flight-transaction lock is evaluated before the property's `UNDER_OFFER` precondition (such a property has by then left `UNDER_OFFER` for `IN_TRANSACTION`), so `ERR_PROPERTY_LOCKED` takes precedence over the `ERR_INVALID_STATE` that the `UNDER_OFFER` check would otherwise raise; a withdraw attempted from any other non-`UNDER_OFFER` state with no such in-flight transaction (for example a property `IN_TRANSACTION` whose transaction is still `PENDING_ASSESSMENT`, a terminal `SOLD` property after close, or a property returned to `VALUED` after a cancellation) is rejected with `ERR_INVALID_STATE`. A successful withdrawal moves the active offer to `DECLINED`, clears `active_offer_id` to null, and moves the property to the terminal `WITHDRAWN` status.

### 3.4. Home Assessment, the Condition Questionnaire, and Repair Line Items

Acceptance creates an `Assessment` in `DRAFT` status, linked to the accepted offer through `offer_id`. The assessment captures three component conditions — `roof_condition`, `hvac_condition`, and `foundation_condition` — each drawn from the ordered scale `EXCELLENT`, `GOOD`, `FAIR`, `POOR` (where `POOR` is the worst). It also records `questionnaire_flags`, an array of self-reported issue codes from the condition questionnaire (for example `LEAK` or `MOLD`), defaulting to an empty array.

While the assessment is still in `DRAFT`, a back-office operator catalogues repairs as `RepairLineItem` records. Each line item references its scoping assessment through `assessment_id`, carries a `category` drawn from `ROOF`, `HVAC`, `FOUNDATION`, `COSMETIC`, or `OTHER`, and an `estimate_amount` in dollars (which may arrive with sub-cent precision and must be zero or greater). On creation the platform pins each line's `rounded_amount` as its `estimate_amount` rounded half-up to two decimal places; this per-line rounding is fixed before the line ever contributes to a repair-credit sum.

Finalizing an assessment is a back-office action that requires all three component conditions to be present. On finalize, the assessment computes its `condition_score` as the worst of the three component conditions — the lowest rank across roof, HVAC, and foundation, treating `POOR` as worst and `EXCELLENT` as best — and writes that same value back onto the property's `condition_score`. The assessment moves `DRAFT → FINALIZED`, its repair line items are locked against further additions, and only at this point does the transaction's repair credit become computable from them.

### 3.5. Scheduling the Close: Repair Credit, Lease-Back, and Final Proceeds

With the assessment finalized, the owning seller schedules the close on their transaction by supplying a `close_date`, an optional `leaseback_days` count of late-checkout nights they wish to stay after close (defaulting to 0), and an optional negotiated buyer concession `final_concession` in dollars (defaulting to 0.0, and required to be zero or greater). Scheduling enforces a sequence of preconditions, which are evaluated in priority order so that the earliest applicable failure is the one reported.

The linked assessment must already be `FINALIZED`; if it is not, the request is rejected with `ERR_ASSESSMENT_NOT_FINALIZED`. The chosen `close_date` must fall within the window that opens at least 7 days from the current logical-clock instant and extends no more than 90 days from now; a date outside `[now + 7 days, now + 90 days]` is rejected with `ERR_CLOSE_DATE_OUT_OF_WINDOW`. The requested `leaseback_days` must be between 0 and the maximum of 60 nights inclusive; exceeding 60 is rejected with `ERR_LEASEBACK_EXCEEDS_MAX`. Finally, the computed repair credit must not exceed ten percent of the offer's `avm_value_snapshot`; a credit above that cap is rejected with `ERR_REPAIR_CREDIT_EXCEEDS_CAP`. When these checks share the endpoint, the assessment-finalized check is evaluated before the close-date window, which is evaluated before the lease-back bound, which is evaluated before the repair-credit cap.

On a successful schedule the transaction sets its `repair_credit` to the sum of the `rounded_amount` of every repair line item belonging to the finalized assessment — each line already rounded to cents, then those rounded cents summed, with the total itself carried to two decimal places (round-per-line, then sum; line items belonging to a still-`DRAFT` assessment are excluded). The transaction then records the seller's `close_date` and `leaseback_days` and computes the lease-back charge. The lease-back daily rate, `leaseback_daily_rate`, is the property's effective AVM multiplied by 0.0004, rounded half-up to two decimal places; the lease-back total, `leaseback_total`, is that daily rate multiplied by `leaseback_days`, rounded half-up to two decimal places (round the daily rate first, then multiply). The effective AVM used here is the property's `revised_avm_value` if an inspection re-trade has already been applied, and otherwise the offer's `avm_value_snapshot`. The transaction moves `PENDING_ASSESSMENT → SCHEDULED`.

The transaction's `final_net_proceeds` is the central reconciliation figure and is recomputed here and at every later step that changes its inputs. It is the effective AVM, minus the effective service fee, minus the `final_concession`, minus the `repair_credit`, minus the `leaseback_total`, rounded half-up to two decimal places. The effective service fee is the effective AVM multiplied by the offer's `service_fee_pct`, rounded half-up to two decimal places — so when a re-trade lowers the effective AVM, the service fee is recomputed on the lower figure. This final payout deliberately diverges from the offer's `preliminary_net_proceeds`: the provisional figure assumed a zero repair credit, no lease-back, and a one-percent concession estimate, whereas the final figure uses the possibly-re-traded effective AVM, the actual round-per-line repair credit, the negotiated `final_concession`, and the lease-back total.

### 3.6. Inspection, Re-Trade, and the Valuation Cascade

A scheduled transaction enters its inspection phase when a back-office operator starts the inspection. The inspection window opens 3 days before the close date, so starting the inspection requires that the logical clock has reached at least `close_date` minus 3 days. A successful start moves the transaction `SCHEDULED → INSPECTION`.

During inspection a `PricingAnalyst` may apply a single price-reducing re-trade by supplying a `retrade_amount` (and, optionally, a `retrade_reason`). The re-trade amount may not exceed three percent of the offer's `avm_value_snapshot`; a larger reduction is rejected with `ERR_RETRADE_EXCEEDS_CAP`. At most one re-trade is permitted per transaction — if `retrade_amount` is already nonzero on the transaction, a second attempt is rejected with `ERR_RETRADE_ALREADY_APPLIED`. A successful re-trade leaves the transaction in `INSPECTION` and triggers the full valuation cascade: the transaction's `retrade_amount` is recorded; the property's `revised_avm_value` is set to `avm_value_snapshot` minus `retrade_amount`, rounded half-up to two decimal places; and because the effective AVM has now dropped, the effective service fee, the `leaseback_daily_rate`, the `leaseback_total`, and the `final_net_proceeds` are all recomputed on the revised figure within the same request. From this point on, the effective AVM that feeds every proceeds and lease-back computation is the `revised_avm_value`.

### 3.7. Closing and Cancellation

Closing a transaction is a back-office action available only while the transaction is in `INSPECTION` — that is, the inspection has run and no re-trade is left pending acceptance. On close, the platform recomputes `final_net_proceeds` one last time from the prevailing inputs and locks it, moves the transaction `INSPECTION → CLOSED`, and moves the property to the terminal `SOLD` status; the accepted offer remains `ACCEPTED`.

Before close, the owning seller may cancel the transaction from any of its live states — `PENDING_ASSESSMENT`, `SCHEDULED`, or `INSPECTION`. Cancellation moves the transaction to the terminal `CANCELLED` status, moves the bound offer to `DECLINED`, returns the property to `VALUED`, and clears the property's `active_offer_id` to null. Cancellation also performs compensation: if a re-trade had been applied to the transaction, the property's `revised_avm_value` is reverted to null, unwinding the revised valuation so the property is priced from its original AVM again. A close attempted on a transaction that is not in `INSPECTION`, like any other transition attempted from an invalid state, is rejected with `ERR_INVALID_STATE`; the optional `cancel_reason` may accompany a cancellation for the record.

### 3.8. Resale and the Spread

Once a transaction has `CLOSED`, the platform may relist the acquired home as a `Resale`. A resale references the closed acquisition through `transaction_id` and may only be created from a transaction in `CLOSED` status; an attempt against any other transaction status is rejected with `ERR_TRANSACTION_NOT_CLOSED`. Listing requires a `list_price` in dollars (zero or greater) and may include a `resale_commission_pct`, the buyer-side commission fraction, which defaults to 0.03 and must lie between 0 and 0.10 inclusive. A resale's `sold_price` is null while it remains listed, and its `status` is one of `LISTED`, `SOLD`, or `DELISTED`.

At listing the platform computes the `projected_spread`. The acquisition cost is what the iBuyer paid the seller — the transaction's effective AVM (its `revised_avm_value` when a re-trade applied, otherwise the `avm_value_snapshot`). The projected commission is the `list_price` multiplied by `resale_commission_pct`, rounded half-up to two decimal places. The `projected_spread` is then the `list_price` minus the acquisition cost minus the transaction's `repair_credit` minus that projected commission, rounded half-up to two decimal places. A new resale opens in `LISTED` status.

When the home sells, a back-office or pricing operator records the sale by supplying the `sold_price` (which must be zero or greater), moving the resale `LISTED → SOLD` and computing the `net_spread`: the net commission is the `sold_price` multiplied by `resale_commission_pct`, rounded half-up to two decimal places, and the `net_spread` is the `sold_price` minus the acquisition cost minus the `repair_credit` minus that net commission, rounded half-up to two decimal places. The `net_spread` is null until the sale is recorded, and it diverges from the `projected_spread` whenever `sold_price` differs from `list_price`. Alternatively, a listed resale may be delisted, moving it `LISTED → DELISTED` with no spread effect.

## 4. Endpoint Definitions

All endpoints share the response envelope of §2.2. Creating a new resource returns HTTP 201; fetching, listing, and state-changing operations on an existing resource return HTTP 200. Error responses carry the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/sellers` | Register a seller (homeowner). | OperationsAdmin, Seller |
| GET | `/sellers/{id}` | Fetch a seller. | OperationsAdmin, Seller, PricingAnalyst |
| POST | `/properties` | Register a property and compute its AVM. | OperationsAdmin, PricingAnalyst |
| GET | `/properties` | List properties; filterable by `seller_id` and `status`. | OperationsAdmin, PricingAnalyst, Seller |
| GET | `/properties/{id}` | Fetch a property with derived AVM and condition fields. | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/properties/{id}/offers` | Issue an instant offer; re-issue supersedes the prior active offer (OCC on property version required for re-issue). | PricingAnalyst |
| GET | `/properties/{id}/offers` | List all offers issued for a property (current and superseded). | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/properties/{id}/withdraw` | Seller withdraws the property from offer. | Seller |
| GET | `/offers/{id}` | Fetch an offer. | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/offers/{id}/accept` | Seller accepts an issued, non-expired offer; spawns an assessment and transaction. | Seller |
| POST | `/offers/{id}/decline` | Seller declines an issued offer; reports expiry if already expired. | Seller |
| GET | `/offers/{id}/assessment` | Find the assessment created for an accepted offer. | OperationsAdmin, PricingAnalyst, Seller |
| GET | `/assessments/{id}` | Fetch an assessment. | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/assessments/{id}/repair-line-items` | Attach a repair line item to a draft assessment. | OperationsAdmin |
| GET | `/assessments/{id}/repair-line-items` | List the repair line items of an assessment. | OperationsAdmin, PricingAnalyst, Seller |
| GET | `/repair-line-items` | List repair line items; filterable by `assessment_id`. | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/assessments/{id}/finalize` | Finalize an assessment; compute condition score and lock line items. | OperationsAdmin |
| GET | `/transactions` | List transactions; filterable by `offer_id`, `property_id`, and `status`. | OperationsAdmin, PricingAnalyst, Seller |
| GET | `/transactions/{id}` | Fetch a transaction with all computed proceeds fields. | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/transactions/{id}/schedule-close` | Seller selects close date and lease-back; finalizes repair credit and proceeds. | Seller |
| POST | `/transactions/{id}/start-inspection` | Open the inspection window. | OperationsAdmin |
| POST | `/transactions/{id}/retrade` | Apply an inspection re-trade; cascades to revised AVM, fees, lease-back, and proceeds. | PricingAnalyst |
| POST | `/transactions/{id}/close` | Close the transaction; property becomes sold and final proceeds lock. | OperationsAdmin |
| POST | `/transactions/{id}/cancel` | Seller cancels a non-closed transaction; unwinds any re-trade. | Seller |
| POST | `/resales` | List a closed transaction's property for resale; compute projected spread. | OperationsAdmin, PricingAnalyst |
| GET | `/resales` | List resales; filterable by `transaction_id` and `status`. | OperationsAdmin, PricingAnalyst, Seller |
| GET | `/resales/{id}` | Fetch a resale. | OperationsAdmin, PricingAnalyst, Seller |
| POST | `/resales/{id}/sell` | Record a resale sale; compute net spread. | OperationsAdmin, PricingAnalyst |
| POST | `/resales/{id}/delist` | Delist a resale listing. | OperationsAdmin, PricingAnalyst |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied `to_iso8601` instant. | OperationsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_OFFER_NOT_REISSUABLE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROPERTY_BELOW_MIN_VALUE` | 422 |
| `ERR_PROPERTY_LOCKED` | 409 |
| `ERR_ASSESSMENT_NOT_FINALIZED` | 409 |
| `ERR_CLOSE_DATE_OUT_OF_WINDOW` | 422 |
| `ERR_LEASEBACK_EXCEEDS_MAX` | 422 |
| `ERR_RETRADE_EXCEEDS_CAP` | 422 |
| `ERR_RETRADE_ALREADY_APPLIED` | 409 |
| `ERR_REPAIR_CREDIT_EXCEEDS_CAP` | 422 |
| `ERR_TRANSACTION_NOT_CLOSED` | 409 |
