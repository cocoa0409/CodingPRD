# Product Warranty Claims API — Product Requirements Document

## 1. Introduction

This document specifies the Product Warranty Registration & Claims API, a back-office platform that governs the full life of a manufacturer's warranty program: cataloguing products and their coverage tiers, registering individual units by serial number to their owners, selling and cancelling extended warranties, validating proof of purchase, intaking and adjudicating defect claims, and transferring warranties between owners. The system is the authoritative record of how much warranty value a given unit has consumed and how much remains.

Two characteristics shape every design decision below. First, the platform behaves as a reconciling ledger: a registration's remaining coverage is never stored as a free-standing number but is continuously reconstructed from an append-only stream of debits and credits, so that the books always balance against the original coverage cap. Second, identical purchase facts can produce materially different refund payouts depending on the coverage tier in force, because the system supports two distinct depreciation algorithms — a straight-line method and a declining-balance method — and two distinct premium-refund algorithms for early extended-warranty cancellation. Implementers must treat the arithmetic in §3 as exact contracts, not approximations.

The intended operators are three: warranty owners acting on their own units, a warranty administrator who configures the catalogue and adjudicates claims, and a claims processor who runs return logistics. The sections that follow define the global contract (§2), the business workflows where the bulk of the rules live (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles, spelled precisely as `Owner`, `WarrantyAdmin`, and `ClaimsProcessor`. A request that omits either header, or whose `X-User-Role` is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles relate to persisted identity differently. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` record; ownership checks on any resource that references an owner compare that resource's owner foreign key to `X-User-ID`. Concretely, a registration's `owner_user_id` is matched against `X-User-ID` to decide whether the caller owns it, and a pending transfer's recipient is matched the same way. When `X-User-Role` is `WarrantyAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `ClaimsProcessor`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records it (it is written to `claims_processor_user_id` on a `Claim` when that processor issues the return authorization) but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording first creation. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, and the `version` field is an integer that starts at 1 on creation and increments by one on every mutation, supporting optimistic concurrency control. These four fields are present on every `Product`, `CoverageTier`, `Registration`, `ExtendedWarranty`, `ProofOfPurchase`, and `Claim`.

Three resources are deliberately leaner. An `Owner`, a `WarrantyTransfer`, and a `LedgerEntry` each carry only `id` and `created_at`; they have neither an `updated_at` nor a `version`, because an owner directory entry is a simple identity record and both transfer events and ledger rows are immutable, append-only history that is never edited after it is written.

### 2.5. Path Resolution and Referenced-Resource Existence

Many operations name a resource in the URL path and reference further resources in the request body. The server validates existence left to right: the path resource is checked first, and any body-referenced resource (a product, coverage tier, registration, claim, owner, extended warranty, or proof) is checked next. The first identifier that does not resolve to an existing record causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any business rule is evaluated. Several list endpoints support reverse-reachability filters — for example, listing the coverage tiers of a product, the registrations of an owner, the ledger of a registration, or the transfers of a registration — and these are described with their endpoints in §4.

### 2.6. Monetary Values, Depreciation Precision, and Rounding

All monetary quantities in this system are integer cents; there are no fractional-cent values stored or returned. Wherever a calculation produces a non-integer intermediate (a depreciated refund, a prorated premium), the raw value is computed in cents and then rounded to a whole cent using the round-half-up convention. Each calculation in §3 specifies exactly where rounding occurs relative to any cap or floor, and that evaluation order is binding: for refund depreciation in particular, the raw depreciated value is rounded to whole cents *before* the remaining-coverage cap is applied, never after.

### 2.7. The Coverage Ledger and Remaining-Coverage Reconciliation

Each registration owns an append-only stream of ledger entries, and its `remaining_coverage_cents` is a derived field reconstructed from that stream rather than mutated in place. Every `LedgerEntry` records a `registration_id`, an `entry_type` of either `DEBIT` or `CREDIT`, a `reason` drawn from `REPAIR_COST`, `REPLACE_COST`, `REFUND_PAYOUT`, `REVERSAL`, or `TRANSFER_FEE`, a non-negative `amount_cents` whose direction is given by the entry type, and a `claim_id` linking it to the claim that produced it (this is an audit value on the ledger row, discoverable through the registration's ledger listing, and is null for fee and credit entries that arise from transfers rather than claims).

To reconcile remaining coverage, the system takes the coverage cap of the registration's currently active tier, sums the `amount_cents` of all `DEBIT` entries for that registration, sums the `amount_cents` of all `CREDIT` entries for that registration, and computes the cap minus total debits plus total credits. No status filter is applied — the ledger is append-only, so every row participates. The sum is order-independent, though entries are returned ordered by `created_at` ascending for replay. The reconciled `remaining_coverage_cents` is then clamped at a floor of zero and may never be reported as negative. This reconciliation runs whenever a ledger entry is created or reversed, and it is recomputed on every read of a registration, so that the conserved-quantity relationship — cap equals remaining coverage plus debits minus credits — holds at all times.

### 2.8. Optimistic Concurrency Control on Warranty Transfer

Initiating a warranty transfer is the one operation guarded by optimistic concurrency control. The request body for initiating a transfer must include `expected_registration_version`, carrying the client's last observed `version` of the target `Registration`. The server compares it against the registration's current `version`. If another writer has advanced that version since the client last read the registration — for example, a claim adjudication that debited coverage and bumped the version, or a transfer that already completed — the values no longer match and the transfer is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from initiating a transfer against a registration whose state it has not actually observed. The `expected_registration_version` field is mandatory on transfer initiation; no other endpoint accepts or requires a version field.

### 2.9. Hierarchical Consistency and Cascades

Because a registration is the parent of its claims, extended warranties, proofs, transfers, and ledger entries, many operations on child resources or sibling events cascade back onto the parent registration. Whenever a cascade mutates the registration — validating a proof, purchasing or cancelling an extension, issuing or adjudicating a claim, initiating or resolving a transfer, voiding the registration, or expiring it — the registration's `version` increments by one and its `updated_at` is refreshed. The specific cascades (which entities change, in what order, and with what derived recomputations) are described in the §3 workflow narratives. All such cascades complete atomically within the request that triggers them; there is no deferred or background settlement.

### 2.10. Validation Ordering

When several checks apply to a single operation they are evaluated in a fixed priority order so that the error a caller sees is deterministic. Authentication is checked first: missing or unknown headers yield `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation yields `ERR_FORBIDDEN`. Existence of all referenced resources is checked third, yielding `ERR_NOT_FOUND`. For transition endpoints, the target resource's state is checked fourth, yielding `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a state from which the requested transition is legal. The optimistic-concurrency version check on transfer initiation is fifth, yielding `ERR_STALE_VERSION`. Ownership scoping is sixth, yielding `ERR_NOT_OWNER` (HTTP 403) when an owner acts on a registration they do not own (or a transfer they are not the named recipient of). The remaining business rules — defect coverage, warranty window, refund eligibility, tier matching, fiscal coverage limits, and so on — follow, and a malformed body that fails basic well-formedness is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The precise trigger for each of these business rules is given alongside the workflow it guards in §3.

## 3. Business Logic & Workflows

### 3.1. Building the Catalogue: Products and Coverage Tiers

The catalogue is configured by a `WarrantyAdmin`. A product is created with a `model_number` (a manufacturer model identifier that must be non-empty and unique across the catalogue), a `category` that is one of `ELECTRONICS`, `APPLIANCE`, `POWER_TOOL`, or `FURNITURE`, an `msrp_cents` value of at least 1 that serves as a refund-value baseline, a `base_warranty_months` term of zero or more whole months included for free, and a `serviceable_lifespan_months` of at least 1 that is the denominator for depreciation proration. Every product begins in `status` `ACTIVE` and may later be `DISCONTINUED`; these are the only two catalogue states.

Against a product, the administrator defines one or more coverage tiers. A `CoverageTier` carries the `product_id` it extends, a `tier_name` that is one of `BASE`, `SILVER`, `GOLD`, or `PLATINUM` and must be unique for a given product-and-tier-name combination, an `extension_months` value of zero or more whole months that this tier adds beyond the base term, a `price_cents` of zero or more for purchasing the tier, a `coverage_cap_cents` of at least 1 that is the maximum cumulative warranty spend reimbursable under the tier, and a `depreciation_method` of either `STRAIGHT_LINE` or `DECLINING_BALANCE` that selects the refund proration algorithm. Two further attributes govern claim and cancellation behavior: `refund_eligible`, a boolean defaulting to true that controls whether a `REFUND` resolution is permitted for claims under this tier, and `premium_refund_method`, which defaults to `PRO_RATA` and is one of `PRO_RATA` or `SHORT_RATE`, selecting how an unused extended-warranty premium is refunded on early cancellation. A tier begins in `status` `ACTIVE` and may later become `RETIRED`; only those two states exist for a tier.

### 3.2. Owners and Registering a Unit

Owners are directory records created by a `WarrantyAdmin`, each with a non-empty `full_name` and a unique, non-empty `email`. A registration may be created by either an `Owner` or a `WarrantyAdmin`. It is filed with the `product_id` of the registered model, the `serial_number` of the specific unit, the `owner_user_id` of the warranty owner, the `purchase_date` (the retail purchase date in ISO 8601 UTC, which is the warranty clock origin), and the `purchase_price_cents` actually paid, an integer of at least 1. A serial number must be non-empty and unique for its product; an attempt to register a serial already on file for the same product is rejected with `ERR_DUPLICATE_SERIAL` (HTTP 409).

A newly created registration starts in `status` `REGISTERED`. Its `proof_status` begins as `UNVERIFIED` (the full set of proof statuses being `UNVERIFIED`, `VALIDATED`, and `REJECTED`). Its `active_tier_id` is set to the product's `BASE` coverage tier, and its `remaining_coverage_cents` is initialized to that base tier's coverage cap. The registration also exposes a computed `warranty_end_date`, equal to the purchase date plus the sum of the product's base warranty months and the active extension months; with only the base tier in force at creation, that is simply the purchase date plus the base warranty months. The full set of registration states is `REGISTERED`, `ACTIVE`, `TRANSFER_PENDING`, `EXPIRED`, and `VOIDED`.

### 3.3. Proof of Purchase and Activation

Before a unit can support claims it must have a validated proof of purchase. Either an `Owner` or a `WarrantyAdmin` submits a proof document against a registration, supplying the `registration_id`, a `document_type` of `RECEIPT`, `INVOICE`, or `BANK_STATEMENT`, a `stated_purchase_date` that the document asserts, and a `stated_amount_cents` of zero or more that the document asserts. A submitted proof begins in `status` `SUBMITTED` and may move to `VALIDATED` or `REJECTED`; those three are the only proof states.

Validation is performed by a `WarrantyAdmin` and is the act that drives a proof from `SUBMITTED` to either `VALIDATED` or `REJECTED`. A proof can only be validated while it is `SUBMITTED`. Two checks decide the outcome. The stated purchase date must fall within 90 days of the registration's purchase date, and the absolute difference between the stated amount and the registration's purchase price must be no more than 500 cents. When both checks pass, the proof becomes `VALIDATED`, its `rejection_reason` is set to null, and the parent registration's `proof_status` is set to `VALIDATED`. When either check fails — that is, the stated purchase date is not within the 90-day window, or the amount differs by more than the 500-cent tolerance — the proof becomes `REJECTED`, the parent registration's `proof_status` is set to `REJECTED`, and `rejection_reason` is set to the first failing check evaluated in this order: the date check is evaluated before the amount check, which is evaluated before the window check, with the available reason codes being `DATE_MISMATCH`, `AMOUNT_MISMATCH`, and `EXPIRED_WINDOW` (and null when the proof is not rejected). Either outcome increments the parent registration's version by one.

Validation has a cross-entity consequence on top of mirroring the proof status. If the registration was in `REGISTERED` at the moment its proof is validated, it advances from `REGISTERED` to `ACTIVE`, becoming claim-eligible. This is a system-driven transition: it has no separate caller action and occurs as a side effect of proof validation, conditioned solely on the registration's proof status being `VALIDATED`.

### 3.4. Extended Warranties: Purchase and Cancellation

An `Owner` or a `WarrantyAdmin` may purchase an extended warranty for a registration by supplying the `registration_id`, the `coverage_tier_id` of the tier being bought, and the `amount_paid_cents`. Purchase is gated by a tier-matching rule: the amount paid must equal the chosen tier's `price_cents`, the tier must be `ACTIVE`, and the tier must belong to the registration's product. Any violation — wrong amount, retired tier, or a tier from a different product — is rejected with `ERR_TIER_MISMATCH` (HTTP 422). A further temporal rule prevents stacking overlapping coverage: the new extension's coverage interval, running from its effective moment for the tier's extension-months span (a half-open interval that includes the start and excludes the end), must not overlap the coverage interval of any existing `ACTIVE` extension on the same registration. Because the intervals are half-open, an extension whose start exactly equals an existing extension's end is adjacent rather than overlapping and is therefore permitted; a genuine overlap is rejected with `ERR_COVERAGE_OVERLAP` (HTTP 409).

A successful purchase creates an `ExtendedWarranty` in `status` `ACTIVE` (the only other state being `CANCELLED`), stamps its `effective_date` with the purchase time, and sets its `premium_refund_cents` to 0 (this field stays 0 until the extension is cancelled). The extension also references the tier through `coverage_tier_id` and the registration through `registration_id`. The purchase then cascades onto the registration: its `warranty_end_date` is recomputed to include the new tier's extension months, its `active_tier_id` is set to the highest-coverage tier now in force, and its `remaining_coverage_cents` is recomputed to the new active tier's cap minus the registration's existing debits. The registration's version increments by one.

Cancellation is an `Owner`-only action and is permitted only when the extension is `ACTIVE`, the acting owner is the parent registration's current owner, and the parent registration is in `REGISTERED` or `ACTIVE` status. Cancelling computes the unused-premium refund (detailed in §3.9), sets the extension's `status` to `CANCELLED`, and then reconciles the parent: the registration's `active_tier_id` drops to the next-highest `ACTIVE` tier or to `BASE` if none remains, the `warranty_end_date` is recomputed accordingly, and `remaining_coverage_cents` is recomputed to the new active tier's cap minus the existing net debits. The registration's version increments by one.

### 3.5. Filing and Withdrawing Claims

A warranty claim is filed by an `Owner` against one of their own registrations, supplying the `registration_id`, a `defect_category` of `MANUFACTURING`, `WEAR_AND_TEAR`, `ACCIDENTAL`, or `COSMETIC`, and a `reported_date` (the date the defect was reported, in ISO 8601 UTC, which must fall within the warranty window). An owner who is not the registration's owner is rejected with `ERR_NOT_OWNER`. At filing, the reported date must be on or before the registration's `warranty_end_date` and the registration must not be `EXPIRED`; a claim outside the window or against an expired registration is rejected with `ERR_WARRANTY_EXPIRED` (HTTP 422). A cooldown also applies: a new claim's reported date must be strictly more than 30 days after the reported date of the most recent non-`CLOSED` claim on the same registration. The cooldown is a closed buffer — a reported date exactly 30 days after the prior claim is still too soon and is rejected with `ERR_CLAIM_COOLDOWN` (HTTP 409). A claim is created in `status` `INTAKE`; its `resolution_type` is null, its `rma_number` is null, its `claims_processor_user_id` is null, and its `assessed_value_cents` is 0 at this point. The complete set of claim states is `INTAKE`, `RMA_ISSUED`, `ADJUDICATED`, `FULFILLED`, `DENIED`, and `CLOSED`.

An owner may withdraw their own claim, but only while it sits at `RMA_ISSUED`. Withdrawal moves the claim from `RMA_ISSUED` to `CLOSED` and records no ledger movement. The acting owner must be the registration's owner, or the request is rejected with `ERR_NOT_OWNER`. The withdrawal increments the parent registration's version by one.

### 3.6. Return Logistics: Issuing the RMA

A `ClaimsProcessor` issues a Return Merchandise Authorization to move an intake claim into logistics. This transition from `INTAKE` to `RMA_ISSUED` is allowed only when the claim is in `INTAKE`, the parent registration is `ACTIVE`, the registration's `proof_status` is `VALIDATED`, and the claim's reported date is on or before the registration's `warranty_end_date`. These guards map to errors per the §2.10 priority order, distinguishing an illegal-state precondition from a warranty-window failure. A registration that is `EXPIRED` is a warranty-window failure (priority 8) rejected with `ERR_WARRANTY_EXPIRED`, as is a claim whose reported date is past the warranty end. By contrast, any other condition that makes the transition illegal — the parent registration being in a status other than `ACTIVE` (for example still `REGISTERED`, or `TRANSFER_PENDING` or `VOIDED`), or its `proof_status` not being `VALIDATED` — is a state precondition (priority 4) rejected with `ERR_INVALID_STATE`. The claim itself not being in `INTAKE` is likewise rejected with `ERR_INVALID_STATE`. Issuing the authorization mints the claim's `rma_number` and records the acting processor's identifier in `claims_processor_user_id` (an audit value, not an entity foreign key). The parent registration's version increments by one.

### 3.7. Adjudication: Repair, Replace, or Refund — and Denial

A `WarrantyAdmin` adjudicates a claim that is under authorization, supplying a `decision` to either approve or deny it. On approval the admin also supplies the `resolution_type` — one of `REPAIR`, `REPLACE`, or `REFUND` — and, for a repair or replace resolution, the cost basis as `repair_cost_cents` or `replace_cost_cents` respectively. Adjudication is legal only when the claim is in `RMA_ISSUED`.

A denial moves the claim from `RMA_ISSUED` to `DENIED`, leaving `resolution_type` null, and is the required outcome when the defect category is `WEAR_AND_TEAR`, `ACCIDENTAL`, or `COSMETIC`, or when the registration's remaining coverage is zero or below. An approval moves the claim from `RMA_ISSUED` to `ADJUDICATED` and is permitted only when the defect category is `MANUFACTURING` and the registration's remaining coverage is strictly greater than zero. An attempt to approve a claim whose defect is anything other than `MANUFACTURING` is rejected with `ERR_DEFECT_NOT_COVERED` (HTTP 422). If the requested resolution is `REFUND`, the active coverage tier's `refund_eligible` flag must be true, or the approval is rejected with `ERR_REFUND_NOT_ELIGIBLE` (HTTP 422).

On a successful approval the system sets the claim's `resolution_type` to the admin-chosen branch and computes the claim's `assessed_value_cents`. For a `REFUND` the assessed value is the depreciated/prorated payout described in §3.8; for a `REPAIR` or `REPLACE` it is the supplied cost basis. The assessed value must not exceed the registration's remaining coverage, and if remaining coverage is already zero the claim cannot be approved — either situation is rejected with `ERR_COVERAGE_EXHAUSTED` (HTTP 422). When approval proceeds, the system writes a `DEBIT` ledger entry whose `reason` matches the resolution (`REPAIR_COST`, `REPLACE_COST`, or `REFUND_PAYOUT`), whose `claim_id` is this claim, and whose `amount_cents` is the assessed value, then decrements the registration's `remaining_coverage_cents` by that assessed value through ledger reconciliation. The parent registration's version increments by one. When the resolution is `REFUND`, the refund terminates coverage: the registration is driven to `VOIDED` as part of the refund's eventual fulfillment, as described in §3.10.

These approval-time checks are evaluated in the priority order set out in §2.10 — existence and state first, then defect coverage, then refund eligibility, then the fiscal coverage limit — so that, for example, a non-manufacturing defect surfaces as `ERR_DEFECT_NOT_COVERED` rather than being masked by a later fiscal check.

### 3.8. Refund Depreciation: Two Divergent Algorithms

When a claim is approved with a `REFUND` resolution, the assessed payout is depreciated against the unit's age, and the algorithm depends on the active tier's depreciation method. In both variants the baseline is the lesser of the registration's purchase price and the product's MSRP — that is, the smaller of `purchase_price_cents` and `msrp_cents`. The elapsed age is the number of whole months from the registration's purchase date to the claim's reported date, taking the floor (any partial month is dropped). Let the product's serviceable lifespan in months be the lifespan denominator.

Under the `STRAIGHT_LINE` method, the system computes a remaining-life fraction equal to the larger of zero and (lifespan minus elapsed months), divided by the lifespan; the raw payout is the baseline multiplied by that fraction. This decays linearly and reaches zero at the end of the serviceable life. Under the `DECLINING_BALANCE` method, the raw payout is the baseline multiplied by a monthly decay rate of 0.97 raised to the power of the elapsed months. This geometric decay never reaches zero and stays strictly positive for the same inputs, so for identical purchase facts the declining-balance payout diverges from the straight-line one.

The raw payout — whichever variant produced it — is rounded to whole cents using round-half-up, and only then is it capped at the registration's remaining coverage: the assessed value is the smaller of the rounded raw payout and the registration's remaining-coverage value read from the pre-adjudication ledger. The evaluation order is fixed and must not be reinterpreted: read remaining coverage from the ledger as it stands before this adjudication, compute the assessed value as the minimum of the rounded raw payout and that pre-adjudication remaining-coverage value, write the debit ledger entry for the assessed amount, and only afterward let coverage reconciliation recompute the post-adjudication remaining coverage. Applying the cap against the post-debit coverage would understate the payout and is incorrect.

### 3.9. Premium Refund on Early Extended-Warranty Cancellation

When an `ACTIVE` extended warranty is cancelled, the system refunds the unused portion of the premium and records it in `premium_refund_cents`. Let the premium paid be the extension's `amount_paid_cents` and the total covered span be the tier's extension months. The elapsed span is the number of whole months from the extension's effective date to the current time, taking the floor. The unused span is the larger of zero and (total covered months minus elapsed months).

Under the `PRO_RATA` method, the raw refund is the premium multiplied by the unused span divided by the total covered months — the full unused-fraction premium. Under the `SHORT_RATE` method, that same pro-rated figure is then reduced by a surrender penalty of 10 percent — that is, multiplied by (1 minus 0.10) — making the short-rate refund strictly less than the pro-rata refund for identical premium, span, and elapsed inputs. In either case the raw refund is rounded to whole cents using round-half-up. If the tier adds no months (a total covered span of zero), the unused span is zero and the refund is zero.

### 3.10. Fulfilling an Adjudicated Claim

A `ClaimsProcessor` fulfills an adjudicated claim — shipping the repair or replacement, or issuing the refund. Fulfillment moves the claim from `ADJUDICATED` to `FULFILLED` and is permitted only when the claim is `ADJUDICATED` and its `resolution_type` is not null. When the resolution is `REFUND`, fulfillment additionally drives the parent registration to `VOIDED` and cancels every `ACTIVE` extended warranty on that registration, because a refund terminates coverage. The parent registration's version increments by one.

### 3.11. Warranty Transfer Between Owners

An `Owner` transfers a warranty to a new owner. Initiation is permitted only when the registration is `ACTIVE`, the supplied `expected_registration_version` matches the registration's current version (per the concurrency rule in §2.8, with a mismatch yielding `ERR_STALE_VERSION`), no claim of the registration is in `RMA_ISSUED` or `ADJUDICATED`, and the supplied `to_owner_user_id` references an existing owner who is distinct from the current owner. The acting owner must be the registration's current owner, or the request is rejected with `ERR_NOT_OWNER`. Initiation drives the registration from `ACTIVE` to `TRANSFER_PENDING` and creates a `WarrantyTransfer` whose `status` is `COMPLETED` (its only other state being `REVERSED`); the transfer event records the `registration_id`, the originating owner copied from the registration's current owner into `from_owner_user_id`, and the intended `to_owner_user_id` — both owner fields being audit values on the transfer event, discoverable through the registration's transfer listing.

Initiation also assesses a transfer fee, computed as described in §3.12 and stored in `transfer_fee_cents`. The system writes a `DEBIT` ledger entry with `reason` `TRANSFER_FEE` for the fee amount and decrements the registration's `remaining_coverage_cents` by the fee through reconciliation. The registration's version increments by one.

The named recipient resolves the pending transfer. Accepting it requires the registration to be `TRANSFER_PENDING` and the acting owner to be the transfer's `to_owner_user_id`; acceptance sets the registration's `owner_user_id` to the recipient and returns the registration from `TRANSFER_PENDING` to `ACTIVE`, incrementing the version by one. Rejecting it likewise requires the registration to be `TRANSFER_PENDING` and the acting owner to be the transfer's recipient; rejection sets the most recent warranty transfer's `status` to `REVERSED`, writes a compensating `CREDIT` ledger entry with `reason` `REVERSAL` for the same `transfer_fee_cents`, restores the registration's `remaining_coverage_cents` by the reversed fee (so the transfer fee is conserved), leaves the `owner_user_id` unchanged because the transfer is abandoned, and returns the registration from `TRANSFER_PENDING` to `ACTIVE`, incrementing the version by one.

### 3.12. Transfer Fee Calculation

The transfer fee is a tiered figure assessed at initiation against the current time. First the elapsed age is computed as the whole months from the registration's purchase date to the current time, taking the floor. The base rate is then selected by age: an elapsed age of fewer than 12 months selects 1500 cents; an elapsed age of at least 12 but fewer than 36 months selects 2500 cents; an elapsed age of 36 months or more selects 4000 cents. A category surcharge of 1000 cents is added when, and only when, the product's category is `APPLIANCE`; otherwise the surcharge is zero. The raw fee is the selected rate plus any surcharge. The fee is then bounded: it is raised to a floor of 1000 cents if it falls below that, and then capped so it can never exceed the registration's remaining coverage — that is, the fee is the smaller of the registration's remaining coverage and the larger of the raw fee and the 1000-cent floor. This order is fixed: select the rate, add the surcharge, apply the floor, then apply the coverage cap last.

### 3.13. Voiding and Expiry

A `WarrantyAdmin` may void a registration that is in `REGISTERED` or `ACTIVE`, provided no claim of that registration is in `RMA_ISSUED`, `ADJUDICATED`, or `FULFILLED`. Voiding drives the registration to `VOIDED` and cancels every `ACTIVE` extended warranty on the registration. The registration's version increments by one.

Expiry is system-driven and tied to the logical clock. A `WarrantyAdmin` may set the server's current UTC instant or advance it to a supplied instant. Advancing the clock runs an expiry sweep: any `ACTIVE` registration whose `warranty_end_date` has passed — that is, the current time is strictly later than the warranty end date — transitions from `ACTIVE` to `EXPIRED` and is no longer claim-eligible, with each affected registration's version incrementing by one. Both clock capabilities accept the target instant as `to_iso8601`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the two clock capabilities — return a `200 OK` status code. All list and fetch operations return `200 OK`. The request body, response body, and side effects of each endpoint are described in the §3 narratives; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a product catalogue entry | WarrantyAdmin |
| GET | `/products/{id}` | Fetch a product by id | WarrantyAdmin, Owner, ClaimsProcessor |
| GET | `/products` | List products (filter by category) | WarrantyAdmin, Owner, ClaimsProcessor |
| POST | `/coverage-tiers` | Define a coverage tier for a product | WarrantyAdmin |
| GET | `/coverage-tiers/{id}` | Fetch a coverage tier by id | WarrantyAdmin, Owner, ClaimsProcessor |
| GET | `/coverage-tiers` | List coverage tiers (filter by product_id) | WarrantyAdmin, Owner, ClaimsProcessor |
| POST | `/owners` | Register an Owner account | WarrantyAdmin |
| GET | `/owners/{id}` | Fetch an owner by id | WarrantyAdmin, Owner |
| POST | `/registrations` | Register a product unit by serial to an owner | Owner, WarrantyAdmin |
| GET | `/registrations/{id}` | Fetch a registration (coverage and end date recomputed on read) | WarrantyAdmin, Owner, ClaimsProcessor |
| GET | `/registrations` | List registrations (filter by owner_user_id, product_id, active_tier_id) | WarrantyAdmin, Owner, ClaimsProcessor |
| POST | `/registrations/{id}/transfer` | Initiate a warranty transfer to a new owner | Owner |
| POST | `/registrations/{id}/transfer/accept` | Recipient accepts a pending transfer | Owner |
| POST | `/registrations/{id}/transfer/reject` | Recipient rejects a pending transfer | Owner |
| POST | `/registrations/{id}/void` | Void a registration; cancels active extensions | WarrantyAdmin |
| GET | `/registrations/{id}/ledger` | List ledger entries for a registration | WarrantyAdmin, Owner, ClaimsProcessor |
| GET | `/registrations/{id}/transfers` | List transfer records for a registration | WarrantyAdmin, Owner |
| POST | `/extended-warranties` | Purchase an extended-warranty tier for a registration | Owner, WarrantyAdmin |
| POST | `/extended-warranties/{id}/cancel` | Cancel an active extended warranty; refund unused premium | Owner |
| GET | `/extended-warranties/{id}` | Fetch an extended warranty by id | WarrantyAdmin, Owner |
| GET | `/extended-warranties` | List extended warranties (filter by registration_id, coverage_tier_id) | WarrantyAdmin, Owner |
| POST | `/proofs` | Submit a proof-of-purchase document | Owner, WarrantyAdmin |
| POST | `/proofs/{id}/validate` | Validate or reject a submitted proof | WarrantyAdmin |
| GET | `/proofs/{id}` | Fetch a proof by id | WarrantyAdmin, Owner |
| GET | `/proofs` | List proofs (filter by registration_id) | WarrantyAdmin, Owner |
| POST | `/claims` | File a warranty claim against a registration | Owner |
| GET | `/claims/{id}` | Fetch a claim by id | WarrantyAdmin, Owner, ClaimsProcessor |
| GET | `/claims` | List claims (filter by registration_id, status) | WarrantyAdmin, Owner, ClaimsProcessor |
| POST | `/claims/{id}/issue-rma` | Issue an RMA for an intake claim | ClaimsProcessor |
| POST | `/claims/{id}/adjudicate` | Approve (with resolution) or deny a claim under RMA | WarrantyAdmin |
| POST | `/claims/{id}/fulfill` | Fulfill an adjudicated claim | ClaimsProcessor |
| POST | `/claims/{id}/withdraw` | Owner withdraws a claim under RMA | Owner |
| POST | `/_clock/set_current_utc` | Set the server's current UTC clock (test-driving) | WarrantyAdmin |
| POST | `/_clock/advance` | Advance the clock and run the expiry sweep | WarrantyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_DEFECT_NOT_COVERED` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXPIRED` | 422 Unprocessable Entity |
| `ERR_REFUND_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_TIER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_COVERAGE_EXHAUSTED` | 422 Unprocessable Entity |
| `ERR_COVERAGE_OVERLAP` | 409 Conflict |
| `ERR_CLAIM_COOLDOWN` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
