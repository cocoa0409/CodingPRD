# Probate Court API — Product Requirements Document

## 1. Introduction

The Probate Court & Estate Administration API is the system of record for the judicial administration of a decedent's estate, from the moment a file is opened through to the discharge of the person entrusted to wind it up. It models the full arc of probate practice: the lodging of a will and the filing of a petition, the appointment of a personal representative and the issuance of letters, the notice period during which creditors may press their claims, the marshaling and appraisal of assets, the payment of allowed claims in strict statutory priority, the distribution of the remaining residue to the heirs and devisees, and the final accounting that must balance before the court will close the estate.

Probate is unforgiving of bookkeeping errors and of shortcuts around due process. A junior creditor paid before a senior one, a distribution that outruns the cash actually on hand, a representative who quietly appoints himself, a claim honored after the bar date has passed — each is a defect the court exists to prevent. This API therefore enforces a segregation of duties among the clerk who records, the judge who adjudicates, and the representative who administers; it tracks every cent of the estate through an integer-cents ledger; and it treats the estate's own version counter as the serialization point that keeps concurrent officers of the court from overwriting one another's work. The remainder of this document specifies the global contract that every endpoint honors (Section 2), the business workflows that give the estate its lifecycle (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity in which they act. If either header is absent, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles, spelled precisely as `Clerk`, `ProbateJudge`, and `PersonalRepresentative`. When a caller is authenticated but their role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

All three roles carry an **opaque** identity. When `X-User-Role` is `Clerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `ProbateJudge`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, though the server does read it for the segregation-of-duties check described below (comparing it against a representative's declared `representative_user_id`, which is itself a stored string rather than an entity `id`). When `X-User-Role` is `PersonalRepresentative`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity; the server may compare it against the `representative_user_id` recorded on the estate's appointed representative to confirm the acting party is the one holding letters, but it never treats `X-User-ID` as an entity `id`.

A structural rule of probate underlies the judge's role: a `ProbateJudge` may not adjudicate an appointment in which they themselves are the nominated administrator. On appointment, if the acting judge's `X-User-ID` is equal to the representative's `representative_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This check is specific to the appointment operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource is minted with a server-generated `id` that is a UUID carrying no type prefix. Resources also record a `created_at` timestamp in ISO 8601 UTC form with three fractional digits, fixed at creation. Every entity in this system — `Estate`, `Petition`, `PersonalRepresentative`, `Bond`, `Beneficiary`, `CreditorClaim`, `Asset`, `Distribution`, `AccountingReport`, and `Hearing` — additionally carries an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 and increments by one on each mutation of that resource. There are no version-free or timestamp-free entities in this domain.

### 2.5. The Estate as Aggregate Root and Optimistic Concurrency

Although every resource is addressed as a top-level collection, the `Estate` is the conceptual aggregate root. Petitions, representatives, bonds, beneficiaries, claims, assets, distributions, accountings, and hearings each carry an `estate_id` that binds them to a single estate, and peer resources are located by filtered list queries rather than by nested URLs. Because so many operations read and mutate estate-wide ledger and status fields, the estate's own `version` is the concurrency token for the whole aggregate.

Every state-transition operation in the system carries a mandatory `expected_estate_version` field in its request body. This value must equal the current `version` of the governing `Estate`; if it does not, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state change is applied. Two situations make this control load-bearing rather than ceremonial. First, appointing a personal representative must carry an `expected_estate_version` matching the target estate's current `version`; if another writer has advanced the estate's version since the client last read it — for example, by appointing a competing nominee that legitimately supersedes earlier attempts — the appointment is rejected with `ERR_STALE_VERSION` (HTTP 412), so a client cannot install a representative on top of an estate view it never observed. Second, approving a distribution must carry an `expected_estate_version` matching the target estate's current `version`; if a prior distribution approval or claim payment has consumed residue and advanced the estate's `version` since the client last read it, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), so a stale residue view cannot authorize a distribution the pool can no longer support. Every successful transition increments `Estate.version` by one (in addition to bumping the acted-upon resource's own `version` and `updated_at`).

### 2.6. Nested Reference Resolution and Referential Integrity

Path parameters are validated left to right: an `id` embedded in a URL must resolve to an existing resource within scope, and if it does not, the request fails with `ERR_NOT_FOUND` (HTTP 404). Foreign-key references supplied in a request body — a `petition_id`, a `representative_id`, or a `beneficiary_id` — are held to a stricter rule: they must resolve to an entity that lives under the same estate as the resource being created or acted upon. A body reference that names a real entity belonging to a different estate is rejected with `ERR_INVALID_REFERENCE` (HTTP 422). Separately, when a required body field is missing, carries the wrong type, is negative or zero where a positive value is required, names an invalid enum member, or supplies a malformed ISO date, the request fails with `ERR_MISSING_FIELD` (HTTP 400).

### 2.7. The Marshaling Ledger and Fiscal Conservation

The estate keeps a single running cash ledger, `marshaled_cash_cents`, expressed in integer cents. It is an incremental accumulator: cash is credited into it when a `CASH` asset is marshaled (its appraised value is added) and when any asset is liquidated (its liquidation proceeds are added); cash is debited out of it when an allowed claim is paid and when an approved distribution is paid. Because it is maintained as the sum of credits minus the sum of debits, its value is independent of the order in which those commutative contributions are applied and it is never rebuilt from scratch. The estate's `residue_cents` — the amount available to distribute — is defined to equal `marshaled_cash_cents` at every point, because claim payments and distribution payments already debit the pool as they occur; residue is simply the live pool remaining after claims are paid and after distributions.

Two conservation invariants must hold after every transition. The **bond obligation** the court holds open is the sum of `penal_amount_cents` over the estate's `APPROVED` bonds; approving a bond and then appointing the representative it backs raises this quantity by the bond's penal amount, and discharging the representative (which exonerates that bond) lowers it by exactly the same amount, so an error-free approve-then-discharge round trip nets to zero. The **cash pool** invariant holds that the total cash marshaled in always equals `marshaled_cash_cents` plus the sum of `paid_amount_cents` over `PAID` claims plus the sum of `proposed_amount_cents` over `PAID` distributions; because only payment debits the pool — neither proposing, approving, nor returning a distribution moves cash — a distribution taken from `PROPOSED` through `APPROVED` to `RETURNED` leaves the pool untouched, a net-zero round trip distinct from the bond invariant.

### 2.8. Precision, Rounding, and Tiered Bond Sizing

All monetary quantities in the system are integer cents. Aggregations are exact sums, comparisons are exact integer comparisons, and no floating-point rounding is introduced. Where a calculation performs division — specifically the bond-sizing tiers below — it uses integer floor division, taking the whole-number quotient and discarding any remainder, and it floors within each tier before summing the tiers.

The court's **required bond amount** protects the estate against a representative's malfeasance and is sized to the estate's declared gross value in tiers. When the estate's supervision level is `INDEPENDENT`, no bond is required and the required amount is zero. Otherwise — when supervision is `FULL` or `LIMITED` — the required amount is a tiered marginal cover computed over the estate's `gross_estate_value_cents`: the first 1,000,000 cents of value are covered in full at 100 percent; the next 4,000,000 cents of value are covered at 50 percent, using integer floor division; and any value beyond the first 5,000,000 cents is covered at 25 percent, again using integer floor division. Concretely, take the first tier as the smaller of the gross value and 1,000,000 cents; take the second tier as the portion of gross value above 1,000,000 cents but not exceeding a further 4,000,000 cents; take the third tier as whatever gross value remains above 5,000,000 cents. The required amount is the first tier in full, plus the floor of the second tier multiplied by 50 and divided by 100, plus the floor of the third tier multiplied by 25 and divided by 100. This required amount is recorded on the bond at filing and is the figure a filed bond's face amount must meet before a judge will approve it.

### 2.9. Supervision Level and Bond Necessity

Each estate is assigned a `supervision_level` computed purely from its declared `gross_estate_value_cents`, using strict less-than comparisons at each boundary. When the gross value is less than 500,000 cents, supervision is `INDEPENDENT`. When the gross value is at least 500,000 cents but less than 5,000,000 cents, supervision is `LIMITED`. When the gross value is at least 5,000,000 cents, supervision is `FULL`. The boundaries themselves fall upward: a gross value of exactly 500,000 cents yields `LIMITED`, and exactly 5,000,000 cents yields `FULL`. This level is recomputed whenever the gross value is set. Whether a representative must post a bond follows directly: `bond_required` is true when supervision is `FULL` or `LIMITED`, and false when supervision is `INDEPENDENT` — independent administration waives the bond entirely.

### 2.10. Hierarchical State Consistency and Cascades

State transitions do not act in isolation. Several operations cascade into sibling resources or into the estate's ledger, and every such secondary effect is part of the operation's contract. Removing a representative forfeits any bond that backs the appointment; discharging a representative exonerates that bond; marshaling a cash asset, liquidating any asset, paying a claim, and paying a distribution each move cash and force the estate's residue to be recomputed; filing a final accounting opens the distribution phase; and approving a final accounting closes the estate and thereby makes the representative eligible for discharge. Each such reconciliation independently refreshes the affected resource's `updated_at` and increments its `version`, and every governed transition additionally increments `Estate.version`. The specific cascades and their preconditions are woven into the workflow narratives of Section 3.

### 2.11. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed priority order so that the same defect always surfaces as the same error. Authentication comes first: a missing or unknown-role header yields `ERR_UNAUTHENTICATED`. Authorization is next: a recognized role that is not permitted for the operation yields `ERR_UNAUTHORIZED`. The segregation-of-duties check on appointment (`ERR_SEGREGATION_OF_DUTIES`) is evaluated ahead of the remaining business checks. Existence of path-scoped resources is checked next (`ERR_NOT_FOUND`), then body foreign-key referential integrity (`ERR_INVALID_REFERENCE`), then presence and typing of required body fields and enum members (`ERR_MISSING_FIELD`). Only then are the stateful checks applied, in this order: optimistic concurrency on `expected_estate_version` (`ERR_STALE_VERSION`), the target resource's own from-state (`ERR_INVALID_STATE`), and any cross-entity state gate (`ERR_CROSS_ENTITY_STATE`). Domain-specific fiscal and temporal checks — the claim period, the payment waterfall, fund sufficiency, residue limits, and the two hearing-conflict checks — are applied after those foundational gates, near the workflows they guard.

### 2.12. The Logical Clock

The server keeps a logical clock that governs every time-sensitive rule in the system: the stamping of a claim's `filed_at`, the opening of the claim period, the computation of the claim bar date, the moment letters are issued, and whether a scheduled hearing may be held. The clock starts at exactly `2026-05-01T00:00:00Z` and, before it is ever set, reads exactly that default value — it never falls back to wall-clock time. An administrative capability lets `Clerk`, `ProbateJudge`, and `PersonalRepresentative` callers advance the clock to a supplied instant, provided as `to_iso8601`. All deadline and claim-period comparisons read this clock rather than the host's wall time.

## 3. Business Logic & Workflows

### 3.1. Opening the File: Estate, Petition, and Will

Every probate begins with a `Clerk` opening a file for the decedent. Opening an estate records the decedent's full legal name as `decedent_name`, the `date_of_death` (which must be no later than the current logical clock at the moment of creation), a two-letter `county_code` such as LA or SF, and the `estate_type`, which is either `TESTATE` (a decedent who left a will) or `INTESTATE` (one who did not). The clerk also declares the estate's `gross_estate_value_cents`, a value greater than zero that drives bond sizing and supervision; from it the system immediately derives `supervision_level`, sets the estate's `status` to `DRAFT`, initializes every ledger field — `inventory_total_cents`, `marshaled_cash_cents`, `allowed_claims_total_cents`, and `residue_cents` — to zero, and leaves `claim_period_opened_at` null (and, by extension, `claim_bar_date` unset until the period opens).

Against a `DRAFT` estate the clerk files a `Petition`, which references the estate by `estate_id` and records the `petitioner_name`. The petition captures whether an original will accompanies it via the boolean `will_lodged`; when `will_lodged` is true the petition must also carry the will's execution date as `will_date`, and when `will_lodged` is false the `will_date` must be omitted. The petition also names the administrator nominee in `nominated_representative_name`. A freshly filed petition enters `PENDING` status. Consider a scenario where a testate estate is opened but the family cannot locate the original will: the petition may still be filed, but as Section 3.2 explains, it cannot be granted until a will is lodged.

### 3.2. Adjudication: Granting or Denying the Petition

Adjudication belongs to the `ProbateJudge`. Granting a `PENDING` petition advances it `PENDING → GRANTED` and is the pivotal act that opens administration. The grant is permitted only when the governing estate is still in `DRAFT` (otherwise `ERR_INVALID_STATE`), and — because a will must be proved before a testate estate can be administered — when the estate's `estate_type` is `TESTATE`, the petition's `will_lodged` must be true, failing which the grant is rejected with `ERR_WILL_NOT_LODGED`. The grant also requires an `expected_estate_version` matching the estate's current `version` (`ERR_STALE_VERSION`). On success the estate moves `DRAFT → OPEN`, its `claim_period_opened_at` is stamped from the current logical clock, its `claim_bar_date` is computed as the opening instant plus 120 days (see Section 3.5), and `Estate.version` increments by one.

Alternatively, the judge may deny a `PENDING` petition, advancing it `PENDING → DENIED`. Denial likewise requires the estate to be in `DRAFT` (`ERR_INVALID_STATE`) and requires a recorded `denial_reason`; if that reason is absent the request fails with `ERR_MISSING_FIELD`. The denial carries an `expected_estate_version` matching the estate's `version` (`ERR_STALE_VERSION`) and increments `Estate.version` by one. Both `GRANTED` and `DENIED` are terminal for the petition.

### 3.3. The Representative and the Bond

Once a petition is granted, the clerk nominates a `PersonalRepresentative`, supplying the estate's `estate_id`, the `petition_id` of the granting petition, the nominee's `full_name`, and the `representative_user_id` — the opaque `X-User-ID` under which that representative will act once they hold letters. A nominated representative enters `NOMINATED` status, and the system computes its `bond_required` flag from the estate's supervision level (true for `FULL` or `LIMITED`, false for `INDEPENDENT`). Its `bond_id` remains null and its `letters_issued_at` remains null until appointment.

When a bond is needed, a `PersonalRepresentative` or a `Clerk` files a `Bond`, naming the estate via `estate_id`, the representative it backs via `representative_id`, the `surety_name` of the company posting it, and the `penal_amount_cents` — the bond's face amount, which must be a non-negative integer (zero is permitted; it is not required to be greater than zero, and only a missing, mistyped, or negative `penal_amount_cents` yields `ERR_MISSING_FIELD`). On filing, the system computes `required_amount_cents` (the tiered minimum from Section 2.8), sets the bond's `status` to `FILED`, and the bond awaits judicial approval. A judge approving a bond advances it `FILED → APPROVED`, permitted only when the bond's `penal_amount_cents` is greater than or equal to its `required_amount_cents`; a shortfall is rejected with `ERR_BOND_INSUFFICIENT`. Approval carries `expected_estate_version` (`ERR_STALE_VERSION`) and increments `Estate.version`.

Appointment is the judge's act of installing the nominee, advancing the representative `NOMINATED → APPOINTED`. It is gated on several conditions evaluated together. The petition named by the representative's `petition_id` must be in `GRANTED` status — the petition state gates appointment — and if it is not, the request is rejected with `ERR_CROSS_ENTITY_STATE`. When the representative's `bond_required` is true, a `Bond` backing this representative must already be `APPROVED`, failing which the request is rejected with `ERR_BOND_NOT_APPROVED`. The segregation-of-duties rule applies: the acting judge's `X-User-ID` must not equal the representative's `representative_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. And the request must carry `expected_estate_version` matching the estate's `version`, since a competing appointment may have advanced the estate since the client last read it (`ERR_STALE_VERSION`, HTTP 412). On success, the representative's `letters_issued_at` is stamped from the logical clock, its `bond_id` is set to the approved bond's id when a bond was required (and left null otherwise), and `Estate.version` increments. With letters issued, the representative may now marshal assets and adjudicate claims.

### 3.4. Suspending, Reinstating, Removing, and Discharging the Representative

A judge may `suspend` an `APPOINTED` representative, advancing it `APPOINTED → SUSPENDED`, and later `reinstate` a suspended one, advancing it `SUSPENDED → APPOINTED`; each requires a matching `expected_estate_version` (`ERR_STALE_VERSION`) and bumps `Estate.version`. Removal is available from either the `APPOINTED` or the `SUSPENDED` state, advancing the representative to `REMOVED`; in both cases, if the representative holds a `bond_id`, that bond is cascaded to `FORFEITED`, and `Estate.version` increments. The two removal branches are symmetric: whether the representative was `APPOINTED → REMOVED` or `SUSPENDED → REMOVED`, the same bond-forfeiture cascade fires and the same version bump applies, each guarded by `expected_estate_version` (`ERR_STALE_VERSION`).

Discharge is the honorable exit and is available only from `APPOINTED`, advancing the representative `APPOINTED → DISCHARGED`. Because a representative may be discharged only after the estate's affairs are wound up, the estate must be in `CLOSED` status — the estate closure gates discharge — and an attempt before closure is rejected with `ERR_CROSS_ENTITY_STATE`. Discharge requires a matching `expected_estate_version` (`ERR_STALE_VERSION`). On discharge, if the representative holds a `bond_id`, that bond is cascaded to `EXONERATED` (the compensating counterpart to the approve-and-bind step, restoring the outstanding bond obligation to its pre-appointment value), and `Estate.version` increments. `DISCHARGED` and `REMOVED` are terminal for the representative. Independently of representative action, a bond that is still `FILED` or `APPROVED` when its representative is removed is forfeited, and a bond that is `APPROVED` when its representative is discharged is exonerated; `EXONERATED` and `FORFEITED` are terminal bond states.

### 3.5. The Creditor Claim Period and Adjudication of Claims

When the petition is granted, the estate's claim period opens: `claim_period_opened_at` is stamped from the logical clock and the `claim_bar_date` is fixed at that instant plus 120 days. The bar date is a half-open boundary: a claim whose `filed_at` is at or before the `claim_bar_date` instant is within the period, while a claim whose `filed_at` is strictly after it is out of time.

A `Clerk` or a `PersonalRepresentative` files a `CreditorClaim`, supplying the estate's `estate_id`, the `creditor_name`, the `claim_class` (one of `SECURED`, `FUNERAL`, `ADMIN`, `TAX`, or `GENERAL`, which fixes the claim's priority rank), and the `claimed_amount_cents`, a value greater than zero. On filing, the claim's `filed_at` is stamped from the logical clock and its `status` is `FILED`. The representative then adjudicates each claim. Allowing a claim advances it `FILED → ALLOWED` and requires several conditions: the estate must be in one of `OPEN`, `INVENTORIED`, or `ACCOUNTING` (`ERR_INVALID_STATE`); the acting `PersonalRepresentative` must be `APPOINTED` and own this estate, since the representative's state gates claim allowance (`ERR_CROSS_ENTITY_STATE`); and the amount the representative allows, `allowed_amount_cents`, must be greater than zero and no greater than the `claimed_amount_cents`, failing which the request is rejected with `ERR_ALLOWED_AMOUNT_INVALID`. The operation carries `expected_estate_version` (`ERR_STALE_VERSION`). On success the estate's `allowed_claims_total_cents` is recomputed as the sum of `allowed_amount_cents` over all claims that are `ALLOWED` or `PAID`, and `Estate.version` increments.

The allow operation has a branch for late filings. If a claim's `filed_at` is strictly after the estate's `claim_bar_date`, the claim is not allowed but is instead auto-barred, advancing `FILED → BARRED`; the supplied `allowed_amount_cents` is ignored and `Estate.version` still increments. These two side effects — the `FILED → BARRED` transition and the `Estate.version` increment — are committed, but the operation does **not** return a 2xx success carrying the barred claim; instead it responds with the period-closed error `ERR_CLAIM_PERIOD_CLOSED` (HTTP 409). That is, when the caller's intent is to allow a claim but the claim's `filed_at` falls strictly after the bar date, the operation surfaces `ERR_CLAIM_PERIOD_CLOSED` as the period-closed signal while having already barred the claim and bumped the estate as described. This late-filing branch is evaluated only after the foundational gates (`ERR_STALE_VERSION`, the claim's own `FILED` from-state, the estate's allow-eligible status, and the acting-representative cross-entity check) have passed. A representative may also reject a claim outright, advancing it `FILED → REJECTED`; rejection requires that the acting representative be `APPOINTED` and own the estate (`ERR_CROSS_ENTITY_STATE`) and carries `expected_estate_version` (`ERR_STALE_VERSION`), incrementing `Estate.version`. `REJECTED`, `BARRED`, and `PAID` are terminal claim states.

### 3.6. Inventory: Listing, Appraising, and Marshaling Assets

The estate's property is captured as `Asset` records. A `Clerk` or `PersonalRepresentative` lists an asset, supplying its `estate_id`, a human `description`, an `asset_class` (one of `REAL_PROPERTY`, `CASH`, `SECURITY`, or `PERSONAL_PROPERTY`), and a `declared_value_cents` greater than zero; the asset enters `LISTED` status. Each asset carries two valuations. While an asset is `LISTED` and not yet appraised, its provisional carrying value is its PR-declared `declared_value_cents`; once it has been appraised — that is, in any of `APPRAISED`, `MARSHALED`, `LIQUIDATED`, or `DISTRIBUTED` — its final carrying value is the independent `appraised_value_cents`. The two figures differ for the same asset whenever the appraiser disagrees with the representative's declaration, and the difference is the appraisal adjustment.

Appraising an asset advances it `LISTED → APPRAISED`, permitted only when the estate is in `OPEN` or `INVENTORIED` (`ERR_INVALID_STATE`) and when a positive `appraised_value_cents` is supplied (absent, it is `ERR_MISSING_FIELD`); it carries `expected_estate_version` (`ERR_STALE_VERSION`). On appraisal, the estate's `inventory_total_cents` is recomputed as the sum of `appraised_value_cents` over every asset whose status is `APPRAISED`, `MARSHALED`, `LIQUIDATED`, or `DISTRIBUTED` — `LISTED` assets, carrying only a provisional value, are excluded from the finalized inventory — and `Estate.version` increments. Marshaling an appraised asset advances it `APPRAISED → MARSHALED`, permitted when the estate is in `INVENTORIED` or `ACCOUNTING` (`ERR_INVALID_STATE`) and carrying `expected_estate_version` (`ERR_STALE_VERSION`); if and only if the asset's `asset_class` is `CASH`, its `appraised_value_cents` is added to the estate's `marshaled_cash_cents`, the residue is recomputed, and `Estate.version` increments.

### 3.7. Liquidation and In-Kind Distribution of Assets

A marshaled asset may be turned into cash or handed to a beneficiary in kind. Liquidating a marshaled asset advances it `MARSHALED → LIQUIDATED`, permitted only when the estate is in `ACCOUNTING` (`ERR_INVALID_STATE`); for any non-`CASH` asset the `liquidation_proceeds_cents` (a positive value) must be supplied, and its absence on a non-cash liquidation is `ERR_MISSING_FIELD`. Liquidation carries `expected_estate_version` (`ERR_STALE_VERSION`); on success the reported `liquidation_proceeds_cents` are added to the estate's `marshaled_cash_cents`, the residue is recomputed, and `Estate.version` increments. Distributing an asset in kind advances it `MARSHALED → DISTRIBUTED`, permitted only when the estate is in `DISTRIBUTING` (`ERR_INVALID_STATE`) and carrying `expected_estate_version` (`ERR_STALE_VERSION`); it increments `Estate.version`. `DISTRIBUTED` is the terminal asset state.

### 3.8. Beneficiaries and the Payment Waterfall

Beneficiaries are added by a `Clerk` or a `PersonalRepresentative`, each recording an `estate_id`, a `full_name`, a `relationship` (one of `SPOUSE`, `CHILD`, `HEIR`, `DEVISEE`, or `CREDITOR_RESIDUAL`), and a `share_bps` — the beneficiary's fractional share of the residue in basis points, where 10,000 basis points is the whole. The sum of the active beneficiaries' `share_bps` must equal 10,000 before distribution proceeds. Each beneficiary tracks `distributed_cents`, initialized to zero, which is later recomputed as the sum of `proposed_amount_cents` over the `PAID` distributions directed to that beneficiary.

Paying allowed claims follows a strict statutory waterfall so that no junior creditor is satisfied ahead of a senior one. Allowed claims are ordered first by the rank of their `claim_class` — `SECURED` ranks 0, `FUNERAL` ranks 1, `ADMIN` ranks 2, `TAX` ranks 3, and `GENERAL` ranks 4 — and ties within the same class are broken by `created_at` ascending (never by id). A claim may be paid only when it is the lowest-ordered claim that is `ALLOWED` and not yet `PAID`; if any strictly-higher-ranked allowed claim remains unpaid, the payment is rejected with `ERR_CLAIM_PRIORITY_VIOLATION`. Paying a claim advances it `ALLOWED → PAID` and is further gated on the estate being in `ACCOUNTING` (`ERR_INVALID_STATE`) and on sufficient funds, and it carries `expected_estate_version` (`ERR_STALE_VERSION`). To size the payment, the system reads the pool — the estate's `marshaled_cash_cents` as it stands strictly before this debit. If that pool is zero, the payment fails with `ERR_INSUFFICIENT_MARSHALED_FUNDS`; otherwise the claim's `paid_amount_cents` is set to the smaller of the claim's `allowed_amount_cents` and the pool, so that when the pool is smaller than the allowed amount the claim receives the partial remainder rather than being rejected. The pool is then debited by that `paid_amount_cents`, the estate's `residue_cents` is recomputed, and `Estate.version` increments.

### 3.9. Proposing, Approving, and Paying Distributions

Once claims are settled and the distribution phase is open, the representative proposes a `Distribution`, recording the estate's `estate_id`, the recipient's `beneficiary_id`, and a `proposed_amount_cents` greater than zero; the proposal enters `PROPOSED` status. A judge approves a proposed distribution, advancing it `PROPOSED → APPROVED`. Approval is permitted only when the estate is in `DISTRIBUTING` (`ERR_INVALID_STATE`); when every allowed claim has been paid — that is, the estate's `allowed_claims_total_cents` equals the sum of `paid_amount_cents` over the estate's `PAID` claims — failing which it is rejected with `ERR_CLAIMS_UNPAID`; and when the `proposed_amount_cents` does not exceed the estate's `residue_cents`, failing which it is rejected with `ERR_DISTRIBUTION_EXCEEDS_RESIDUE`. Approval carries `expected_estate_version` matching the estate's `version`, because a prior approval or claim payment may have consumed residue since the client last read the estate (`ERR_STALE_VERSION`, HTTP 412); it increments `Estate.version`.

Paying an approved distribution advances it `APPROVED → PAID` and is the only distribution step that moves cash. It requires a `receipt_reference` recording the beneficiary's acknowledgement — absent, it is `ERR_MISSING_FIELD` — and requires that the estate's `marshaled_cash_cents` be at least the `proposed_amount_cents`, failing which it is `ERR_INSUFFICIENT_MARSHALED_FUNDS`. Payment carries `expected_estate_version` (`ERR_STALE_VERSION`). On payment the pool is debited by `proposed_amount_cents`, the recipient beneficiary's `distributed_cents` is recomputed, the estate's `residue_cents` is recomputed, and `Estate.version` increments. Alternatively, an approved distribution that could not be delivered may be returned, advancing it `APPROVED → RETURNED`; return carries `expected_estate_version` (`ERR_STALE_VERSION`), moves no cash, and increments `Estate.version`. Because only payment debits the pool, a proposal that is approved and then returned is a net-zero round trip on the estate's cash. `PAID` and `RETURNED` are terminal distribution states.

### 3.10. Accountings, Balancing, and Closing the Estate

The estate advances through its phases by way of `AccountingReport` records, each drafted by the representative with an `estate_id` and a `report_type` of `INVENTORY`, `INTERIM`, or `FINAL`; a draft enters `DRAFT` status. Filing a report advances it `DRAFT → FILED` and is gated on the estate being in the phase appropriate to the report type: an `INVENTORY` report requires the estate to be `OPEN`, an `INTERIM` report requires `INVENTORIED`, and a `FINAL` report requires `ACCOUNTING`; a mismatch is `ERR_INVALID_STATE`. Additionally, a `FINAL` report may be filed only when every `ALLOWED` claim under the estate has already been `PAID`, failing which it is rejected with `ERR_CLAIMS_UNPAID`. Filing carries `expected_estate_version` (`ERR_STALE_VERSION`).

On filing, the report captures three snapshots: `snapshot_inventory_cents` from the estate's `inventory_total_cents`, `snapshot_allowed_claims_cents` from the estate's `allowed_claims_total_cents`, and `snapshot_distributed_cents` as the sum of `proposed_amount_cents` over the estate's `PAID` distributions. It then computes its `balances` flag by a conservation check: the total cash brought in — the sum of `appraised_value_cents` over marshaled `CASH` assets plus the sum of `liquidation_proceeds_cents` over liquidated assets — must exactly equal the sum of `paid_amount_cents` over `PAID` claims plus the sum of `proposed_amount_cents` over `PAID` distributions plus the estate's current `marshaled_cash_cents`; `balances` is true if and only if that equality holds exactly. If the report type is `FINAL`, filing also advances the estate `ACCOUNTING → DISTRIBUTING`, opening the phase in which distributions may be proposed and approved. `Estate.version` increments.

A judge approves a filed report, advancing it `FILED → APPROVED`, but only after the balance check is recomputed fresh at approval time and found true; if it is not, the approval is rejected with `ERR_ACCOUNTING_UNBALANCED`. Approval carries `expected_estate_version` (`ERR_STALE_VERSION`) and drives the estate's status forward by report type: approving an `INVENTORY` report advances the estate `OPEN → INVENTORIED`; approving an `INTERIM` report advances it `INVENTORIED → ACCOUNTING`; and approving a `FINAL` report advances it `DISTRIBUTING → CLOSED`, which is what makes the representative eligible for discharge. A judge may instead reject a filed report, advancing it `FILED → REJECTED` (carrying `expected_estate_version`, `ERR_STALE_VERSION`). Each approval or rejection increments `Estate.version`. `APPROVED` and `REJECTED` are terminal report states.

### 3.11. Scheduling and Conducting Hearings

Court supervision is exercised through `Hearing` records, scheduled by a `Clerk`. A hearing records its `estate_id`, a `hearing_type` of `PETITION`, `ACCOUNTING`, or `REMOVAL`, a `courtroom_code` naming the physical room, a `judge_user_id` naming the assigned judge, a `start_at`, and an `end_at` that must be strictly after `start_at`. A newly scheduled hearing enters `SCHEDULED` status, but only if it clears two independent conflict checks against other `SCHEDULED` hearings (`VACATED` and `HELD` hearings are excluded from both).

The **courtroom** check uses half-open interval semantics with no buffer, keyed on `courtroom_code`. The new hearing conflicts with an existing scheduled hearing sharing its `courtroom_code` when the new hearing's `start_at` is before the existing hearing's `end_at` and the existing hearing's `start_at` is before the new hearing's `end_at`; a conflict is rejected with `ERR_COURTROOM_CONFLICT`. Because the interval is half-open, exact adjacency — where the new hearing's `start_at` equals the existing hearing's `end_at` — is permitted, so back-to-back hearings in the same room are allowed. The **judge calendar** check, keyed on `judge_user_id`, is stricter: it uses closed intervals plus a 30-minute recess buffer applied to both ends. Expand the new hearing's window by 30 minutes on each side, then the new hearing conflicts with an existing scheduled hearing sharing its `judge_user_id` when the new hearing's `start_at` minus 30 minutes is at or before the existing hearing's `end_at` and the existing hearing's `start_at` is at or before the new hearing's `end_at` plus 30 minutes; a conflict is rejected with `ERR_JUDGE_CALENDAR_CONFLICT`. Because both edges compare with "at or before," a gap of exactly 30 minutes between two of a judge's hearings still collides — the gap between them must strictly exceed the recess.

A judge conducts a scheduled hearing by holding it, advancing it `SCHEDULED → HELD`, permitted only when the current logical clock is at or after the hearing's `start_at` (`ERR_INVALID_STATE`) and carrying `expected_estate_version` (`ERR_STALE_VERSION`); it increments `Estate.version`. A judge may instead vacate a scheduled hearing, advancing it `SCHEDULED → VACATED`, which carries `expected_estate_version` (`ERR_STALE_VERSION`), frees that courtroom and judge interval so it no longer collides with future scheduling, and increments `Estate.version`. `HELD` and `VACATED` are terminal hearing states.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Creation endpoints that mint a new resource return HTTP 201; all other successful operations — including every state transition, read, list, and the clock capability — return HTTP 200. Request bodies, response payloads, and side effects are not repeated here; reconstruct them from the workflow narratives of Section 3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Advance the server logical clock to a supplied instant | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/estates` | Open an estate file in DRAFT | Clerk |
| GET | `/estates/{id}` | Get an estate with computed ledger and posture fields | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/estates` | List estates (paginated); optional county/status filter | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/petitions` | File a petition and lodge a will against a DRAFT estate | Clerk |
| GET | `/petitions/{id}` | Get a petition | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/petitions` | List petitions; filter by estate | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/petitions/{id}/grant` | Grant a petition; open administration and start the claim period | ProbateJudge |
| POST | `/petitions/{id}/deny` | Deny a petition | ProbateJudge |
| POST | `/representatives` | Nominate a personal representative for a granted petition | Clerk |
| GET | `/representatives/{id}` | Get a personal representative | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/representatives` | List representatives; filter by estate, petition, or bond | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/representatives/{id}/appoint` | Appoint the representative and issue letters | ProbateJudge |
| POST | `/representatives/{id}/suspend` | Suspend an appointed representative | ProbateJudge |
| POST | `/representatives/{id}/reinstate` | Reinstate a suspended representative | ProbateJudge |
| POST | `/representatives/{id}/remove` | Remove a representative; forfeit any bond | ProbateJudge |
| POST | `/representatives/{id}/discharge` | Discharge a representative after closure; exonerate any bond | ProbateJudge |
| POST | `/bonds` | File a bond for a representative | PersonalRepresentative, Clerk |
| GET | `/bonds/{id}` | Get a bond | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/bonds` | List bonds; filter by estate or representative | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/bonds/{id}/approve` | Approve a bond whose face meets the required amount | ProbateJudge |
| POST | `/beneficiaries` | Add a beneficiary with a residue share | Clerk, PersonalRepresentative |
| GET | `/beneficiaries/{id}` | Get a beneficiary | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/beneficiaries` | List beneficiaries; filter by estate | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/claims` | File a creditor claim | Clerk, PersonalRepresentative |
| GET | `/claims/{id}` | Get a creditor claim | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/claims` | List creditor claims; filter by estate/class/status | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/claims/{id}/allow` | Allow a claim within the period, or auto-bar a late claim | PersonalRepresentative |
| POST | `/claims/{id}/reject` | Reject a claim | PersonalRepresentative |
| POST | `/claims/{id}/pay` | Pay an allowed claim per the priority waterfall | PersonalRepresentative |
| POST | `/assets` | List (inventory) an asset in LISTED | Clerk, PersonalRepresentative |
| GET | `/assets/{id}` | Get an asset | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/assets` | List assets; filter by estate/class/status | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/assets/{id}/appraise` | Record the appraised value of an asset | PersonalRepresentative |
| POST | `/assets/{id}/marshal` | Marshal an asset; CASH adds to the ledger | PersonalRepresentative |
| POST | `/assets/{id}/liquidate` | Liquidate a marshaled asset to cash | PersonalRepresentative |
| POST | `/assets/{id}/distribute-in-kind` | Distribute a marshaled asset in kind | PersonalRepresentative |
| POST | `/distributions` | Propose a cash distribution to a beneficiary | PersonalRepresentative |
| GET | `/distributions/{id}` | Get a distribution | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/distributions` | List distributions; filter by estate/beneficiary/status | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/distributions/{id}/approve` | Approve a proposed distribution | ProbateJudge |
| POST | `/distributions/{id}/pay` | Pay an approved distribution and file the receipt | PersonalRepresentative |
| POST | `/distributions/{id}/return` | Record that an approved distribution was returned | PersonalRepresentative |
| POST | `/accountings` | Draft an accounting report of a given type | PersonalRepresentative |
| GET | `/accountings/{id}` | Get an accounting report | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/accountings` | List accounting reports; filter by estate/type/status | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/accountings/{id}/file` | File an accounting; snapshot the ledger and compute balance | PersonalRepresentative |
| POST | `/accountings/{id}/approve` | Approve a filed accounting; advance estate status | ProbateJudge |
| POST | `/accountings/{id}/reject` | Reject a filed accounting | ProbateJudge |
| POST | `/hearings` | Schedule a hearing on a courtroom/judge interval | Clerk |
| GET | `/hearings/{id}` | Get a hearing | Clerk, ProbateJudge, PersonalRepresentative |
| GET | `/hearings` | List hearings; filter by estate/courtroom/judge/status | Clerk, ProbateJudge, PersonalRepresentative |
| POST | `/hearings/{id}/hold` | Hold a scheduled hearing whose start time has arrived | ProbateJudge |
| POST | `/hearings/{id}/vacate` | Vacate a scheduled hearing, freeing its interval | ProbateJudge |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REFERENCE | 422 |
| ERR_MISSING_FIELD | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_CROSS_ENTITY_STATE | 409 |
| ERR_WILL_NOT_LODGED | 409 |
| ERR_BOND_NOT_APPROVED | 409 |
| ERR_BOND_INSUFFICIENT | 409 |
| ERR_CLAIM_PERIOD_CLOSED | 409 |
| ERR_ALLOWED_AMOUNT_INVALID | 409 |
| ERR_CLAIM_PRIORITY_VIOLATION | 409 |
| ERR_INSUFFICIENT_MARSHALED_FUNDS | 409 |
| ERR_DISTRIBUTION_EXCEEDS_RESIDUE | 409 |
| ERR_CLAIMS_UNPAID | 409 |
| ERR_ACCOUNTING_UNBALANCED | 409 |
| ERR_COURTROOM_CONFLICT | 409 |
| ERR_JUDGE_CALENDAR_CONFLICT | 409 |
