# Cottage-Food & Farmers-Market Vendor Permit API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Cottage-Food & Farmers-Market Vendor Permit API, a health-department compliance platform that governs the full regulatory lifecycle of small-scale food producers who sell at farmers markets and comparable venues. The system tracks a producer from initial registration through identity verification, records the products they intend to sell, and subjects each product to an allowed-food review and an independent labeling review before it may ever reach a market table. Around that core it layers the machinery a health jurisdiction actually needs: class-based permits with inspections and annual sales caps, a market manifest workflow that reserves a vendor's slot for a single event day, a running sales ledger that enforces the cap in real time, complaint intake with segregation of duties, and product recalls whose consequences cascade outward to permits and scheduled market appearances.

The platform is fundamentally a **compliance-audit** system with **posture-driven gating**: what a producer is allowed to do at any moment depends on their current registration posture, their permit's status and term, and the compliance and labeling posture of each product. Many of the most consequential state changes are not requested directly by a user but are triggered automatically as side effects — a single reported sale can breach an annual cap and suspend a producer, and a single recall can ripple through a product, a permit, and every scheduled manifest bound to it. The requirements below describe both the explicit operations an operator performs and the automatic reconciliations the server must perform on their behalf.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is absent, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Producer`, `HealthInspector`, `MarketManager`, and `HealthAdmin`.

- When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting `Producer`; ownership checks on any resource that references a producer compare that resource's `producer_id` to `X-User-ID`. A producer acts on their own registration, products, permits, market manifests, and sales.
- When `X-User-Role` is `MarketManager`, `X-User-ID` is the `id` of the `FarmersMarket` that operator manages; ownership checks on a manifest's target market compare the manifest's `market_id` to `X-User-ID`. A market manager approves, rejects, and checks in the vendors appearing at their market.
- When `X-User-Role` is `HealthInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `inspector_user_id` on an `Inspection` it closes, or as `filed_by_user_id` / `reviewed_by_user_id` on a `Complaint` — but it does not compare it to any entity's `id`.
- When `X-User-Role` is `HealthAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server may record it on complaint actions it performs but does not compare it to any entity's `id`. Health administrators own policy, market, recall, revocation, void, reinstatement, clock, and reporting operations.

Role authority for each endpoint is enumerated in the §4 table. Registration is shared between `Producer` and `HealthAdmin`; complaint filing, review, and resolution are shared between `HealthInspector` and `HealthAdmin`; read operations are broadly available as the §4 table specifies.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list is sorted by `created_at` in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object.

### 2.4. Common Resource Properties and Identifiers

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation and `updated_at` advances on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it underpins the optimistic-concurrency mechanism described in §2.9.

`Producer`, `Product`, `Permit`, `Inspection`, `Complaint`, `FarmersMarket`, `MarketManifest`, `SalesRecord`, and `RecallEvent` all carry the full complement of `id`, `created_at`, `updated_at`, and `version`. The `AllowedFoodPolicy` resource is an exception: it is immutable configuration and carries only `id` and `created_at`. It has no `updated_at` and no `version`.

### 2.5. The Logical Clock and Permit Terms

All server time comes from a single logical clock, never from wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and it holds that value until an administrator explicitly advances it. An administrator-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the new `current_utc`. Every timestamp the server records — a producer's `verified_at`, a sales record's `recorded_at`, a permit's `term_start` and `expires_at` — is read from this logical clock at the moment of the action.

A permit is issued for a fixed term of exactly 365 days. Whenever a permit is issued or re-issued, the server sets `term_start` to the current logical clock and sets `expires_at` to `term_start` advanced by 365 days. The derived `is_expired` flag is true whenever the current logical clock is strictly later than `expires_at`; expiry is a computed reading only and never by itself changes the permit's `status`.

### 2.6. Monetary Values, Precision, and Ledger Integrity

All money is stored and computed in integer cents; there is no fractional-cent representation and no floating-point money field. Permit fees, sales amounts, booth fees, and recall liabilities are exact integers. Where a rate is applied — the market fee rate against a gross sale — the product is rounded to the nearest whole cent using the round-half-up convention, and, as detailed in §3.5, rounding is applied per line before any summation, never after.

A producer's `ytd_gross_sales_cents` is a running money ledger and is treated as a conserved quantity. Recording a sale adds that sale's gross amount to the ledger; voiding a previously recorded sale subtracts the same amount back out, restoring the ledger to the value it would have held had the sale never been recorded. The ledger must always equal the sum of the gross amounts of the producer's sales that are still in `RECORDED` status.

### 2.7. Posture-Driven Gating and Segregation of Duties

Many operations are gated on the acting producer's posture. A producer's `status` moves through `PENDING_VERIFICATION`, `REGISTERED`, and `SUSPENDED`. Submitting a permit, submitting a market manifest, and reporting a sale each require the acting producer to be in `REGISTERED` status; a producer who is still `PENDING_VERIFICATION` or who has been `SUSPENDED` is turned away with `ERR_PRODUCER_NOT_REGISTERED`.

Complaint handling is governed by segregation of duties. The user who files a complaint is recorded in `filed_by_user_id`. Any later review or resolution of that complaint must be performed by a different user: the acting `X-User-ID` must not equal `filed_by_user_id`. A reviewer or resolver who is the same person as the filer is rejected with `ERR_SEGREGATION_OF_DUTIES`.

### 2.8. Cascading Suspension, Revocation, and Occupancy Conservation

Several operations mutate more than one resource. Two cascade families recur throughout the domain, and both must be applied in full.

**Suspension cascade.** When a producer is suspended — whether because a reported sale breached the annual cap or because a recall implicated one of their products — the producer's `status` becomes `SUSPENDED` and, where a recall or cap breach is involved, their `ISSUED` permit's `status` becomes `SUSPENDED` as well. Every non-terminal market manifest belonging to that producer (that is, any manifest in `SUBMITTED`, `APPROVED`, or `CHECKED_IN`) is moved to `VOIDED`. Each such manifest that had been holding a market day-slot (any formerly `APPROVED` or `CHECKED_IN` manifest) releases that slot, and each release increments the owning `FarmersMarket`'s `version` by one.

**Revocation cascade.** When an administrator revokes an `ISSUED` permit, every non-terminal market manifest bound to that permit is moved to `VOIDED`, and every freed day-slot increments its `FarmersMarket`'s `version` by one.

**Occupancy conservation.** A market's per-day occupancy count is a conserved quantity. Every action that seats a vendor (a manifest approval) occupies exactly one day-slot and bumps the market `version`; every action that unseats a vendor (a withdrawal of a previously approved manifest, or any of the void cascades above) releases exactly one day-slot and again bumps the market `version`. The count of occupied slots for a given market and event date must therefore always equal the number of manifests currently in `APPROVED` or `CHECKED_IN` for that market and date.

Any automatic transition the server performs as part of a cascade is a mutation and refreshes the affected resource's `updated_at` and `version` exactly as an explicit mutation would.

### 2.9. Optimistic Concurrency Control

Two operations require the client to prove it is acting on a current view of a parent resource by supplying that parent's last observed `version` as a mandatory field.

Beginning the renewal of a permit requires `expected_permit_version` in the request body, carrying the client's last observed `version` of that `Permit`. If the permit's `version` has advanced since the client read it — because a prior renewal, or a cascade that suspended the permit, legitimately bumped it — the request is rejected with `ERR_STALE_PERMIT_VERSION` at HTTP 412, preventing the producer from renewing a permit whose state they have not observed.

Approving a market manifest requires `expected_market_version` in the request body, carrying the manager's last observed `version` of the target `FarmersMarket`. Because each prior approval consumes a day-slot and bumps the market's `version`, a manager acting on a stale market view — whose last slot may already be taken — is rejected with `ERR_STALE_MARKET_VERSION` at HTTP 412. No other endpoint takes a version field; only manifest approval and permit renewal are OCC-guarded.

### 2.10. Request Validation Order and Resource Resolution

Every request is validated in a fixed precedence so that failures surface deterministically. Authentication context is checked first: missing or unknown headers yield `ERR_MISSING_AUTH_CONTEXT` (HTTP 400). Role authorization is checked next: a role not permitted for the operation yields `ERR_UNAUTHORIZED` (HTTP 403). The system then resolves every resource id named in the path or body, validated left-to-right, returning on the first missing reference with the matching not-found error (`ERR_PRODUCER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_MARKET_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_SALES_RECORD_NOT_FOUND`, or `ERR_RECALL_NOT_FOUND`, each HTTP 404). Only then is the request body's shape, type, and enum membership validated, with any malformed body — a missing required field, a wrong type, an illegal enum value, a non-positive `gross_amount_cents`, or a bad `verification_token` — rejected with `ERR_INVALID_REQUEST` (HTTP 400).

After those universal checks, business rules apply in the following relative order, so that a stateful conflict is reported before deeper business gates: first the target resource's own state legality for the requested transition (a family of HTTP 409 state errors described alongside each workflow), then the acting producer's `REGISTERED` posture where required (`ERR_PRODUCER_NOT_REGISTERED`), then segregation of duties on complaint actions (`ERR_SEGREGATION_OF_DUTIES`), then the optimistic-concurrency version check (the HTTP 412 stale-version errors), then cross-entity referential preconditions (such as a linked permit being `ISSUED` or a passed inspection existing), then product safety gates, then venue-class restriction, then temporal checks, then duplicate-manifest detection, and finally market-day capacity. The manifest-submission workflow in §3.4 walks this ordering concretely.

## 3. Business Logic & Workflows

### 3.1. Producer Registration and Verification

A producer record is created by a producer registering themselves or by an administrator registering on their behalf. Registration captures the `business_name` (the legal or DBA name), the `operator_name` (the cottage-food operator's full name), a `contact_email`, the `county` in which the home kitchen operates, and a `water_source` that is either `PUBLIC` or `PRIVATE_WELL`. A `PRIVATE_WELL` source is a compliance signal that the operator draws on a private well rather than a municipal supply, a factor relevant to water-activity-sensitive food categories. On creation the producer starts in `PENDING_VERIFICATION` status, a one-time `verification_token` is minted, `verified_at` is left null, and `ytd_gross_sales_cents` is initialized to zero.

Verification is the producer's own action: they present the `verification_token` in the request body, and if it equals the token the server minted at registration, the producer transitions from `PENDING_VERIFICATION` to `REGISTERED` and `verified_at` is stamped from the current logical clock. A token that does not match is rejected with `ERR_INVALID_REQUEST`.

A suspended producer can be returned to service only by an administrator, and only when no recall for that producer is still in progress. Reinstatement moves the producer from `SUSPENDED` back to `REGISTERED`; if any `RecallEvent` for the producer is still in `INITIATED` status, the reinstatement is refused with `ERR_RECALL_INVALID_STATE`.

### 3.2. Allowed-Food Policy, Product Declaration, and Dual-Axis Review

The health department maintains an immutable catalog of allowed-food policies, one row per food category, created by an administrator. Each policy names a `food_category` — one of `BAKED_GOODS`, `JAMS_JELLIES`, `DRY_MIXES`, `CANDY`, `ACID_PICKLES`, `FERMENTED_VEG`, `DAIRY`, `MEAT_POULTRY`, `LOW_ACID_CANNED`, or `JUICE` — and records whether the category `is_cottage_allowed` at all, whether it `class_b_required` (permissible only under an inspected permit), and whether it `requires_allergen_label`. A policy may also set an acidification ceiling `max_ph` and a moisture ceiling `max_water_activity`; either may be left unset, in which case that limit does not apply.

A producer declares a product by supplying its owning `producer_id`, a `name`, a `food_category`, an operator-declared `requires_refrigeration` flag, a retail `unit_price_cents`, and optionally a measured `ph_value` and a measured `water_activity`. A declared product begins with `compliance_status` of `DECLARED` and `label_status` of `LABEL_DRAFT`. These two axes evolve completely independently of one another.

On the compliance axis, a health inspector reviews the product's fitness as a cottage food and records a `decision`. An approval moves `compliance_status` from `DECLARED` to `APPROVED`, but only when all of the following hold: the policy for the product's category has `is_cottage_allowed` true; the product's `requires_refrigeration` is false; and, where the policy sets limits, the product's `ph_value` is at most `max_ph` and its `water_activity` is at most `max_water_activity`. A category that is not cottage-allowed, a product that needs refrigeration, or a measured pH or water activity that exceeds a set ceiling all cause the approval to fail with `ERR_FOOD_NOT_COTTAGE_ALLOWED`. A rejecting decision moves `compliance_status` from `DECLARED` to `REJECTED` and records the supplied `reject_reason`.

On the labeling axis, a health inspector reviews the product's label and records a `decision`. An approval moves `label_status` from `LABEL_DRAFT` to `LABEL_APPROVED`; where the category `requires_allergen_label`, the label review is the point at which allergen declaration is asserted, and a product whose label was not properly approved will later be blocked from market use with `ERR_LABEL_NOT_APPROVED`. A rejecting decision moves `label_status` to `LABEL_REJECTED` and records the supplied `reject_reason`. Both `REJECTED` (on the compliance axis) and `RECALLED` are terminal for the compliance axis; a product that has been recalled can never return.

### 3.3. Permit Lifecycle: Class, Inspection, Issuance, Renewal, Revocation

A permit ties a producer to a class of operation. A producer creates a permit by supplying the `producer_id` and a `permit_class` of either `CLASS_A` (registration only, no inspection, lower cap) or `CLASS_B` (inspected, higher cap). At creation the permit begins in `DRAFT`, and two derived fields are set from the class: `inspection_required` is true exactly when the class is `CLASS_B`, and `annual_cap_cents` is 7,500,000 cents (75,000 dollars) for `CLASS_A` and 15,000,000 cents (150,000 dollars) for `CLASS_B`. The `renewal_count` begins at zero.

A registered producer submits a draft permit, advancing it from `DRAFT` to `SUBMITTED`; a producer who is not `REGISTERED` is refused with `ERR_PRODUCER_NOT_REGISTERED`. Scheduling an inspection for a `SUBMITTED` permit automatically advances it to `UNDER_INSPECTION`.

Issuance is a health inspector's action and takes three forms. For a `CLASS_A` permit, issuance goes straight from `SUBMITTED` to `ISSUED`; attempting the `CLASS_A` path on a `CLASS_B` permit is illegal because a `CLASS_B` permit must pass through `UNDER_INSPECTION` first. For a `CLASS_B` permit, issuance goes from `UNDER_INSPECTION` to `ISSUED` and requires that a `PASSED` inspection exists for the permit; absent one, issuance fails with `ERR_INSPECTION_NOT_PASSED`. In both first-issue paths the server rejects issuance with `ERR_PERMIT_TERM_OVERLAP` if the producer already holds another `ISSUED` permit whose term interval overlaps the new term. On a successful first issue the server stamps `term_start` and `expires_at` per §2.5 and computes `fee_cents` once, as described below.

Renewal is a producer's action and is optimistic-concurrency-guarded. Beginning a renewal moves an `ISSUED` permit to `RENEWAL_PENDING`, requires `expected_permit_version` to match the permit's current `version`, and increments the permit's `version` by one. Re-issuing a `RENEWAL_PENDING` permit is again a health inspector's action and returns it to `ISSUED`; for a `CLASS_B` permit this re-issue requires a `PASSED` inspection whose `inspection_type` is `RENEWAL`, failing otherwise with `ERR_INSPECTION_NOT_PASSED`. Each re-issue on the renewal path increments `renewal_count` by one and resets `term_start` and `expires_at` to a fresh 365-day term from the current clock. The `fee_cents` is computed only on the first issue and is not recomputed on renewal.

The one-time permit fee is assembled from three parts, all in exact integer cents. The base fee is 2,500 cents for a `CLASS_A` permit and 7,500 cents for a `CLASS_B` permit. A tier surcharge is then added according to the permit's `annual_cap_cents`: 5,000 cents when the cap is at least 15,000,000 cents, 2,500 cents when the cap is at least 7,500,000 cents but below 15,000,000, and nothing otherwise. Finally, an inspection surcharge of 3,000 cents is added for a `CLASS_B` permit and nothing for a `CLASS_A` permit. The three parts are summed: a `CLASS_A` permit therefore totals 5,000 cents (2,500 base plus 2,500 tier plus 0 inspection), and a `CLASS_B` permit totals 15,500 cents (7,500 base plus 5,000 tier plus 3,000 inspection).

Revocation is an administrator's action available from `DRAFT`, `SUBMITTED`, `UNDER_INSPECTION`, `ISSUED`, or `SUSPENDED`, moving the permit to the terminal `REVOKED` state. When an `ISSUED` permit is revoked, the revocation cascade of §2.8 fires: every non-terminal manifest bound to the permit is voided and every freed day-slot bumps its market's `version`. A permit that is suspended by a cap breach or a recall (moving from `ISSUED` to `SUSPENDED`) likewise voids every non-terminal manifest bound to it and frees their day-slots. Any request to submit, issue, or renew a permit that is not in a legal state for that transition is rejected with `ERR_PERMIT_INVALID_STATE`.

### 3.4. Markets, Manifests, and the Submission Gate

An administrator creates a farmers market by supplying its `name`, its `county`, a `venue_type` of `CERTIFIED_FM`, `TEMP_EVENT`, or `ONLINE`, a `max_vendors_per_day` capacity, and an `allowed_classes` array listing which of `CLASS_A` and `CLASS_B` may vend there. A market begins in `ACTIVE` status and may later be `CLOSED` by an administrator.

A producer assembles a market manifest for a single vending day by supplying the `producer_id`, the target `market_id`, the `permit_id` relied on for the event, the `event_date` as a `YYYY-MM-DD` string, and a `product_ids` array of the products to be sold. A new manifest begins in `DRAFT` with `booth_fee_cents` at zero.

Submitting a manifest advances it from `DRAFT` to `SUBMITTED` and is the system's principal compliance gate. Once the manifest itself is confirmed to be in a submittable state (otherwise `ERR_MANIFEST_INVALID_STATE`), the submission checks run in this order:

1. The acting producer must be `REGISTERED`, else `ERR_PRODUCER_NOT_REGISTERED`.
2. The linked permit's `status` must be `ISSUED`, else `ERR_PERMIT_NOT_ISSUED`.
3. The permit must not be expired at the event: the `event_date` must be on or before the calendar date of the permit's `expires_at`, else `ERR_PERMIT_EXPIRED`.
4. Every product listed in `product_ids` must have `compliance_status` of `APPROVED`, must have `label_status` of `LABEL_APPROVED`, and must not be `RECALLED`. A product that is not approved on the compliance axis yields `ERR_PRODUCT_NOT_APPROVED`; one that is not label-approved yields `ERR_LABEL_NOT_APPROVED`; one that has been recalled yields `ERR_PRODUCT_RECALLED`.
5. The permit's `permit_class` must appear in the market's `allowed_classes`, else `ERR_VENUE_CLASS_NOT_ALLOWED`.
6. No other non-terminal manifest may already exist for the same combination of producer, market, and event date, else `ERR_DUPLICATE_MANIFEST`.

A market manager acts on a submitted manifest. Approving it moves it from `SUBMITTED` to `APPROVED`; approval requires `expected_market_version` to match the market's current `version` (else `ERR_STALE_MARKET_VERSION`, HTTP 412) and requires that the count of manifests already in `APPROVED` or `CHECKED_IN` for that market and event date be strictly below the market's `max_vendors_per_day` (else `ERR_MARKET_CAPACITY_FULL`). A successful approval occupies one day-slot and increments the market's `version` by one. Rejecting a submitted manifest moves it to `REJECTED`. Checking in an approved vendor moves the manifest from `APPROVED` to `CHECKED_IN`.

A producer may withdraw their own manifest from either `SUBMITTED` or `APPROVED`, moving it to `WITHDRAWN`; when the withdrawn manifest had been `APPROVED`, the withdrawal releases the held day-slot and increments the market's `version` by one, preserving the occupancy-conservation invariant of §2.8. Beyond these explicit actions, a manifest in `SUBMITTED`, `APPROVED`, or `CHECKED_IN` may be moved to `VOIDED` by the system as part of a producer suspension, permit suspension, permit revocation, or recall cascade; whenever a formerly `APPROVED` or `CHECKED_IN` manifest is voided, its day-slot is released and the market's `version` is bumped. Any manifest action attempted from an illegal state is rejected with `ERR_MANIFEST_INVALID_STATE`.

### 3.5. Sales Reporting, the Cap Breach, and Booth Settlement

A registered producer reports a sale against a manifest by supplying the `manifest_id` and a `gross_amount_cents`, which must be strictly greater than zero (a non-positive amount is `ERR_INVALID_REQUEST`). The sale may only be recorded when the linked manifest's `status` is `APPROVED` or `CHECKED_IN`; otherwise the request is refused with `ERR_MANIFEST_INVALID_STATE`. The acting producer must be `REGISTERED`, else `ERR_PRODUCER_NOT_REGISTERED`. A recorded sale begins in `RECORDED` status, denormalizes its `producer_id` from the manifest for ledger rollup, and stamps `recorded_at` from the current logical clock.

Recording a sale has three side effects. First, the sale's `gross_amount_cents` is added to the producer's `ytd_gross_sales_cents`. Second, the owning manifest's `booth_fee_cents` is recomputed by the settlement rule below. Third, the cap-breach check runs: the check compares the producer's provisional year-to-date sales — the sum, after adding the new sale, of `gross_amount_cents` across all of the producer's sales still in `RECORDED` status — against the annual cap of the producer's `ISSUED` permit. The comparison is strict: a year-to-date total equal to the cap does not breach, and a total of exactly one cent above the cap does. When the provisional total is strictly greater than the cap, the producer is suspended and the full suspension cascade of §2.8 fires — producer and issued permit move to `SUSPENDED` and every non-terminal manifest is voided with day-slots freed.

The booth settlement fee is computed per line and then summed, in that pinned order. For the owning manifest, each of its sales still in `RECORDED` status contributes the round-half-up of its `gross_amount_cents` multiplied by the market fee rate of 0.06 (six percent), and those already-rounded per-line amounts are summed to form `booth_fee_cents`. Rounding each line before summing is required and differs from summing first: two recorded sales of 908 cents each round to 54 cents apiece (54.48 rounded half up), summing to 108 cents, whereas rounding the summed 1,816 cents times 0.06 would give 109 cents.

An administrator may void a recorded sale, moving it from `RECORDED` to `VOIDED`; a sale that is not currently `RECORDED` (already voided) yields `ERR_SALES_RECORD_NOT_RECORDED`. Voiding subtracts the sale's `gross_amount_cents` back out of the producer's `ytd_gross_sales_cents`, restoring the ledger invariant, and recomputes the manifest's `booth_fee_cents` over the remaining recorded sales.

### 3.6. Inspections and Complaints

A health inspector schedules an inspection against a permit by supplying the `permit_id`, an `inspection_type` of `ROUTINE`, `RENEWAL`, or `COMPLAINT`, and a `scheduled_for` datetime. The inspection begins in `SCHEDULED` with `violation_count` at zero; if the target permit is currently `SUBMITTED`, scheduling the inspection also advances that permit to `UNDER_INSPECTION`. Closing an inspection is an inspector's action carrying a `result` of `PASS` or `FAIL`; a passing close moves the inspection to `PASSED` and a failing close moves it to `FAILED`, in both cases recording the supplied `violation_count` (zero for a clean pass) and stamping `inspector_user_id` with the closing inspector's `X-User-ID`. An inspection that is not in `SCHEDULED` cannot be closed and yields `ERR_INSPECTION_NOT_SCHEDULED`.

A complaint is filed by a health inspector or an administrator against a producer, optionally naming a specific product. Filing captures the subject `producer_id`, an optional `product_id`, a `category` of `LABELING`, `ILLNESS`, `UNAPPROVED_FOOD`, or `SALES_VENUE`, and a free-text `description`; the complaint begins in `RECEIVED` and records the filer in `filed_by_user_id`. Advancing a complaint to `UNDER_REVIEW` records the reviewer in `reviewed_by_user_id` and, per the segregation-of-duties rule of §2.7, requires that the reviewer's `X-User-ID` differ from `filed_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` otherwise. Resolving a complaint from `UNDER_REVIEW` carries an `outcome` of `SUBSTANTIATE` or `DISMISS`, moving it to `SUBSTANTIATED` or `DISMISSED` respectively; resolution is likewise blocked when the acting user equals the filer (`ERR_SEGREGATION_OF_DUTIES`). A review or resolution attempted from an illegal complaint state is rejected with `ERR_COMPLAINT_INVALID_STATE`.

### 3.7. Recalls and Liability

A recall is initiated by an administrator against a specific product, supplying the `producer_id`, the `product_id`, a `reason` of `ILLNESS_OUTBREAK`, `MISLABEL`, or `CONTAMINATION`, and a `severity` of `LOW`, `MEDIUM`, or `HIGH`. A recall may only target a product whose `compliance_status` is `APPROVED`; a non-approved target is refused with `ERR_PRODUCT_NOT_APPROVED`. The recall begins in `INITIATED`.

Initiating the recall computes an estimated liability and fires a three-step cascade. The estimated liability, `estimated_liability_cents`, is the severity-projected unit count multiplied by the product's `unit_price_cents`, where the projected units are 10 for `LOW`, 50 for `MEDIUM`, and 200 for `HIGH`. The cascade then, in order, moves the target product's `compliance_status` to `RECALLED`; suspends the producer's `ISSUED` permit and moves the producer's `status` to `SUSPENDED`; and voids every non-terminal manifest bound to that permit, freeing each held day-slot and bumping the owning market's `version`.

Resolving a recall is an administrator's action that moves it from `INITIATED` to `RESOLVED`, supplying the actual `recalled_units` returned. At resolution the server computes `final_liability_cents` as `recalled_units` multiplied by the product's `unit_price_cents`; this final figure diverges from the initial estimate whenever the actual returned units differ from the severity projection. A resolve attempted against a recall that is not in `INITIATED` is rejected with `ERR_RECALL_INVALID_STATE`.

### 3.8. Compliance and Sales-Cap Reporting

A per-producer compliance summary provides a read-model rollup over the producer's records. It returns the `producer_id`, the producer's current `status`, a `provisional_ytd_cents`, an `audited_ytd_cents`, the governing `annual_cap_cents`, a `cap_utilization_pct`, the `active_permit_id`, an `open_complaint_count`, and an `active_recall_count`.

Two sales figures are reported side by side because they answer different questions. The provisional figure, `provisional_ytd_cents`, is the sum of `gross_amount_cents` across every one of the producer's sales still in `RECORDED` status, with no manifest filter and no exemption; this is the real-time figure that governs the cap-breach check of §3.5. The audited figure, `audited_ytd_cents`, is the end-of-season reconciliation view: it sums `gross_amount_cents` only over recorded sales whose manifest has reached `CHECKED_IN`, then subtracts a sampling-and-donation exemption of 50,000 cents, with the result floored at zero so it never goes negative. The `cap_utilization_pct` expresses `provisional_ytd_cents` as a percentage of `annual_cap_cents`. The `active_permit_id` names the producer's currently `ISSUED` permit, `open_complaint_count` counts the producer's complaints not yet in a terminal outcome, and `active_recall_count` counts the producer's recalls still in `INITIATED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. All list endpoints are paginated per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cottage-food/producers` | Register a cottage-food producer | Producer, HealthAdmin |
| GET | `/cottage-food/producers` | List producers | Producer, HealthInspector, HealthAdmin, MarketManager |
| GET | `/cottage-food/producers/{id}` | Get a producer | Producer, HealthInspector, HealthAdmin, MarketManager |
| POST | `/cottage-food/producers/{id}/verify` | Verify a producer's registration | Producer |
| POST | `/cottage-food/producers/{id}/reinstate` | Reinstate a suspended producer | HealthAdmin |
| GET | `/cottage-food/producers/{id}/compliance-summary` | Computed compliance/sales-cap summary | Producer, HealthInspector, HealthAdmin |
| POST | `/cottage-food/allowed-food-policies` | Create an allowed-food policy | HealthAdmin |
| GET | `/cottage-food/allowed-food-policies` | List allowed-food policies | Producer, HealthInspector, HealthAdmin, MarketManager |
| POST | `/cottage-food/products` | Declare a product | Producer |
| GET | `/cottage-food/products` | List products | Producer, HealthInspector, HealthAdmin, MarketManager |
| GET | `/cottage-food/products/{id}` | Get a product | Producer, HealthInspector, HealthAdmin, MarketManager |
| POST | `/cottage-food/products/{id}/review-food` | Allowed-food review (compliance axis) | HealthInspector |
| POST | `/cottage-food/products/{id}/review-label` | Labeling review (label axis) | HealthInspector |
| POST | `/cottage-food/permits` | Create a draft permit | Producer |
| GET | `/cottage-food/permits` | List permits | Producer, HealthInspector, HealthAdmin, MarketManager |
| GET | `/cottage-food/permits/{id}` | Get a permit | Producer, HealthInspector, HealthAdmin, MarketManager |
| POST | `/cottage-food/permits/{id}/submit` | Submit a draft permit | Producer |
| POST | `/cottage-food/permits/{id}/issue` | Issue or re-issue a permit | HealthInspector |
| POST | `/cottage-food/permits/{id}/renew` | Begin renewal of an issued permit (OCC) | Producer |
| POST | `/cottage-food/permits/{id}/revoke` | Revoke a permit | HealthAdmin |
| POST | `/cottage-food/inspections` | Schedule an inspection for a permit | HealthInspector |
| GET | `/cottage-food/inspections` | List inspections | Producer, HealthInspector, HealthAdmin |
| GET | `/cottage-food/inspections/{id}` | Get an inspection | Producer, HealthInspector, HealthAdmin |
| POST | `/cottage-food/inspections/{id}/close` | Close an inspection | HealthInspector |
| POST | `/cottage-food/complaints` | File a complaint | HealthInspector, HealthAdmin |
| GET | `/cottage-food/complaints` | List complaints | HealthInspector, HealthAdmin |
| GET | `/cottage-food/complaints/{id}` | Get a complaint | HealthInspector, HealthAdmin |
| POST | `/cottage-food/complaints/{id}/review` | Advance a complaint to review (SoD) | HealthInspector, HealthAdmin |
| POST | `/cottage-food/complaints/{id}/resolve` | Resolve a complaint (SoD) | HealthInspector, HealthAdmin |
| POST | `/cottage-food/farmers-markets` | Create a farmers market | HealthAdmin |
| GET | `/cottage-food/farmers-markets` | List farmers markets | Producer, HealthInspector, HealthAdmin, MarketManager |
| GET | `/cottage-food/farmers-markets/{id}` | Get a farmers market | Producer, HealthInspector, HealthAdmin, MarketManager |
| POST | `/cottage-food/market-manifests` | Create a draft market manifest | Producer |
| GET | `/cottage-food/market-manifests` | List manifests | Producer, HealthInspector, HealthAdmin, MarketManager |
| GET | `/cottage-food/market-manifests/{id}` | Get a manifest | Producer, HealthInspector, HealthAdmin, MarketManager |
| POST | `/cottage-food/market-manifests/{id}/submit` | Submit a manifest (compliance gate) | Producer |
| POST | `/cottage-food/market-manifests/{id}/approve` | Approve a manifest (OCC + capacity) | MarketManager |
| POST | `/cottage-food/market-manifests/{id}/reject` | Reject a manifest | MarketManager |
| POST | `/cottage-food/market-manifests/{id}/check-in` | Check in an approved vendor | MarketManager |
| POST | `/cottage-food/market-manifests/{id}/withdraw` | Withdraw a manifest | Producer |
| POST | `/cottage-food/sales-records` | Report a sale | Producer |
| GET | `/cottage-food/sales-records` | List sales records | Producer, HealthInspector, HealthAdmin |
| GET | `/cottage-food/sales-records/{id}` | Get a sales record | Producer, HealthInspector, HealthAdmin |
| POST | `/cottage-food/sales-records/{id}/void` | Void a sale | HealthAdmin |
| POST | `/cottage-food/recall-events` | Initiate a recall (depth-3 cascade) | HealthAdmin |
| GET | `/cottage-food/recall-events` | List recall events | Producer, HealthInspector, HealthAdmin |
| GET | `/cottage-food/recall-events/{id}` | Get a recall event | Producer, HealthInspector, HealthAdmin |
| POST | `/cottage-food/recall-events/{id}/resolve` | Resolve a recall | HealthAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock | HealthAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PRODUCER_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_MARKET_NOT_FOUND` | 404 Not Found |
| `ERR_MANIFEST_NOT_FOUND` | 404 Not Found |
| `ERR_SALES_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCER_NOT_REGISTERED` | 409 Conflict |
| `ERR_PERMIT_INVALID_STATE` | 409 Conflict |
| `ERR_MANIFEST_INVALID_STATE` | 409 Conflict |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_COMPLAINT_INVALID_STATE` | 409 Conflict |
| `ERR_SALES_RECORD_NOT_RECORDED` | 409 Conflict |
| `ERR_RECALL_INVALID_STATE` | 409 Conflict |
| `ERR_PERMIT_NOT_ISSUED` | 409 Conflict |
| `ERR_INSPECTION_NOT_PASSED` | 409 Conflict |
| `ERR_PERMIT_EXPIRED` | 409 Conflict |
| `ERR_PERMIT_TERM_OVERLAP` | 409 Conflict |
| `ERR_FOOD_NOT_COTTAGE_ALLOWED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_LABEL_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_PRODUCT_RECALLED` | 422 Unprocessable Entity |
| `ERR_VENUE_CLASS_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_MANIFEST` | 409 Conflict |
| `ERR_MARKET_CAPACITY_FULL` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_STALE_MARKET_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PERMIT_VERSION` | 412 Precondition Failed |
