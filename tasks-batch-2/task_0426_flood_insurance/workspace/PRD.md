# Flood Insurance API — Product Requirements Document

## 1. Introduction

The National Flood Insurance Program (NFIP) underwrites flood coverage for structures whose risk is too concentrated for the private market alone. This API is the system of record for that program: it tracks the participating communities a structure can be insured in, the elevation evidence that drives its rate, the policies written against it, and the claims paid out when a flood loss occurs. The central tension the system must manage is that two parallel rating regimes coexist — the modern Risk Rating 2.0 methodology, which prices each structure on its individual flood-zone band and elevation freeboard, and the legacy subsidized methodology, which survives only inside Special Flood Hazard Areas — and the same coverage inputs must produce auditable, reproducible premiums under whichever regime a policy elects.

Beyond pricing, the platform enforces the regulatory choreography that distinguishes flood insurance from ordinary property cover: a statutory waiting period before coverage attaches, a mandatory-purchase obligation for mortgaged structures in high-hazard zones, a strict sixty-day deadline for sworn proof-of-loss filings, and the increased-cost-of-compliance benefit that unlocks only when a structure is declared substantially damaged. Every monetary movement — premium earned, premium refunded, premium credited on transfer, and claim dollars paid — must reconcile to the penny against a conserved ledger, because the program is audited on its books. The remainder of this document specifies the global contracts that govern all responses, the cross-cutting principles that bind the entities together, and the detailed business workflows that an implementation must reproduce exactly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `PolicyHolder`, `Underwriter`, `Adjuster`, and `FemaAdmin`. A request whose `X-User-Role` is missing or is not one of these four recognized roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request from a syntactically valid role that is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

Three of the four roles are opaque operator identities. When `X-User-Role` is `Underwriter`, `Adjuster`, or `FemaAdmin`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. The `PolicyHolder` role is likewise carried as an opaque identifier rather than a stored entity row, but it carries ownership meaning: when `X-User-Role` is `PolicyHolder`, the value of `X-User-ID` is the identifier recorded as `owner_id` on the properties that holder registers, as `holder_id` on the policies they hold, and as `claimant_id` on the claims they file. Ownership checks on holder-scoped operations compare the acting `X-User-ID` against those stored owner fields: a `PolicyHolder` who requests a quote on a property, or files a claim against a policy, must be the owner/holder/claimant of that resource, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership check applies when registering a quote on a property, when filing a claim, and on the holder-scoped GET reads a `PolicyHolder` performs against their own properties, policies, claims, proofs-of-loss, and transfers.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list results are ordered by their creation timestamp, `created_at`, in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object.

### 2.4. Common Resource Properties and the Audit Record

Most resources in this system are mutable, versioned records. Communities, Properties, Policies, Claims, Proofs-of-loss, and Policy Transfers each carry a system-managed `id` (a UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits) marking creation, an `updated_at` timestamp updated on every mutation, and an integer `version` that begins at its initial value and increments by one on every mutation. The `version` field is the substrate for optimistic concurrency control described in §2.6.

The Elevation Certificate is deliberately different. A filed elevation certificate is an immutable evidence record: it carries only an `id` and a `created_at`. It has neither an `updated_at` nor a `version`, because once filed it is never modified — a correction is expressed by filing a newer certificate, not by editing an existing one.

### 2.5. Flat Topology and Reference Resolution

The resource collections live at the root of the API rather than in a deep nesting hierarchy, and entities reference one another by foreign-key identifiers carried in request bodies. Even so, several read paths and creation paths embed a parent identifier in the URL, and every identifier — whether it appears in the path or as a foreign key in the body — must resolve to an existing resource. Resolution proceeds left-to-right: the system validates each identifier in path order first, then the body foreign keys, and the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or business rule is evaluated. Reverse-reachability reads make the foreign-key graph navigable in the other direction: a community's properties are listable by `community_id`, a property's elevation certificates by `property_id`, a property's policies by `property_id`, a claim's proofs-of-loss by `claim_id`, claims by `policy_id`, and transfers by their `from_policy_id` or `superseded_policy_id`.

### 2.6. Optimistic Concurrency Control

Certain mutating operations require the client to prove it is acting on a current view of the target resource by submitting the version it last observed. The community update operation requires `expected_community_version`; the policy transfer and policy cancellation operations require `expected_policy_version`; and the claim approval and claim denial operations require `expected_claim_version`. In each case the submitted value must equal the live `version` of the parent resource at the moment the operation is applied.

For a policy transfer, the request must carry `expected_policy_version` matching the current `version` of the policy named by `from_policy_id`. If the policy's `version` has advanced since the client last read it — because another writer has endorsed it or a prior transfer has already superseded the holder under the assumption rules — the client's view of the policy, and of the unearned premium it would credit, is stale, and the transfer is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412). The same `expected_policy_version` requirement and the same `ERR_STALE_POLICY_VERSION` (HTTP 412) rejection govern policy cancellation. For claim approval and claim denial, the request must carry `expected_claim_version` matching the claim's current `version`; because rejecting a supporting proof-of-loss legitimately bounces the claim back and advances its `version`, an approval or denial still carrying an outdated version is acting on a stale view and is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). Operations not named in this subsection take no version field.

### 2.7. Monetary Precision and Rounding

All premium and settlement figures are carried in whole dollars. Wherever a calculation in this document calls for rounding, the method is round half up to whole dollars. The pricing pipeline and the claim-settlement pipeline both pin their rounding points: intermediate subtotals are each rounded to whole dollars at the points specified in §3, and the flat additive components are summed onto the already-rounded subtotals (round-then-sum). The CRS discount fraction itself is an exact table value and is not rounded; only the dollar figures it scales are rounded. On premium proration, only the earned-premium figure is rounded; the unearned remainder is computed as the exact complement so that earned premium plus unearned premium always equals the original quoted premium with no second rounding.

### 2.8. Cascading Consistency and the Premium Ledger

A single state transition in this system frequently mutates more than one entity, and each affected entity independently has its `updated_at` refreshed and its `version` incremented. Activating a policy writes a pointer onto the property; cancelling, lapsing, or transferring a policy clears that pointer and, where the structure is mandatorily insured, drives the property's compliance status. Approving a claim is the most far-reaching cascade: it writes settlement figures onto the claim, advances the policy's running paid-claims total, and bumps the property's loss tally, which can in turn flip the property's repetitive-loss flag. The governing invariant for premium dollars is conservation: when an active policy is cancelled, the premium splits into an earned portion and a refund returned to the holder, and the two sum to the quoted premium; when an active policy is transferred, the premium splits into an earned portion and an unearned portion that rides with the policy as a credit balance, and those two likewise sum to the quoted premium. No operation may create or destroy premium dollars outside these splits.

### 2.9. The Logical Clock

Every date computation in the system — bind, effective, and expiration instants, proof-of-loss timeliness, and premium proration — is evaluated against a server-controlled logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. A `FemaAdmin` may advance the clock to an absolute UTC instant by supplying `to_iso8601`; from that point forward all date-derived computations use the new instant.

## 3. Business Logic & Workflows

### 3.1. Communities and the Community Rating System Discount

A `FemaAdmin` establishes the regulatory backdrop by registering NFIP communities. A community is created with a `name`, a FEMA `county_code`, an optional `participating` flag (which defaults to true and governs whether policies may be written there), and an optional `crs_class` (which defaults to 10). The Community Rating System class is an integer from 1 through 10 inclusive, where a lower class earns a larger premium discount and class 10 earns none. From the class the system derives `crs_discount_pct`, an exact discount fraction looked up from a fixed schedule: class 1 yields a discount of 0.45, class 2 yields 0.40, class 3 yields 0.35, class 4 yields 0.30, class 5 yields 0.25, class 6 yields 0.20, class 7 yields 0.15, class 8 yields 0.10, class 9 yields 0.05, and class 10 yields 0.00. The `crs_discount_pct` is the value read into the premium calculation at quote time.

A `FemaAdmin` may later update a community's `participating` flag or its `crs_class`; doing so re-derives `crs_discount_pct` from the same schedule and increments the community's `version`. Because the update is an optimistic-concurrency operation, it requires `expected_community_version` to match the community's live `version`, as detailed in §2.6.

### 3.2. Properties, Flood Zones, and the Mandatory-Purchase Obligation

A property is registered — by its owning `PolicyHolder` or by an `Underwriter` acting on the owner's behalf — with a `community_id` placing it in an NFIP community, an `owner_id` recording the holder who owns it, a street `address`, a `flood_zone`, an `occupancy`, a `base_flood_elevation_ft` reading taken from the Flood Insurance Rate Map, and an optional `has_active_mortgage` flag that defaults to false. The `flood_zone` is one of `VE`, `AE`, or `X`. From it the system computes `is_sfha`: a property is in a Special Flood Hazard Area, with `is_sfha` true, when its zone is `VE` or `AE`, and is non-SFHA, with `is_sfha` false, when its zone is `X`. The `occupancy` is one of `PRIMARY_RESIDENCE` or `NON_PRIMARY`; it later governs both a premium surcharge and whether the building is settled at replacement cost or actual cash value.

Several property attributes are computed and evolve over the structure's life. The `loss_history_count` starts at 0 and counts the approved claims recorded against this property's policies; the `is_repetitive_loss` flag starts at false and flips to true once the loss count reaches 2 or more. The `compliance_status` reflects the mandatory-purchase obligation and starts at `NOT_REQUIRED`. The obligation attaches only to a structure that is both in an SFHA and carries an active mortgage — that is, `is_sfha` true together with `has_active_mortgage` true; for such a structure the status becomes `COMPLIANT` once an active policy is in force and becomes `LAPSED` if that required coverage is later withdrawn. A structure that is not both SFHA and mortgaged remains `NOT_REQUIRED`. Finally, `active_policy_id` is a denormalized pointer to the property's currently in-force policy, or null when none is active; it is set when a policy activates and cleared when that policy leaves the active state.

### 3.3. Filing Elevation Certificates

Elevation evidence is filed against a property by a `PolicyHolder` or an `Underwriter` as an immutable record. A certificate carries the `property_id` of the structure it measures, the `surveyor_license` of the licensed surveyor who signed it, the measured `lowest_floor_elevation_ft` of the lowest floor in NAVD88 feet, and an optional `superseded` flag (defaulting to false) that marks the record as replaced by a newer one. On filing, the system computes `freeboard_ft` as the certificate's lowest-floor elevation minus the property's base flood elevation; a positive freeboard means the lowest floor sits above the base flood elevation and earns a cheaper Risk Rating 2.0 premium. When several certificates exist for a property, pricing reads the latest certificate by `created_at` among those whose `superseded` flag is false.

### 3.4. Quoting a Policy: the Two Rating Regimes

A flood policy begins as a quote, requested by the property's `PolicyHolder` or by an `Underwriter` on the owner's behalf. The quote request supplies the `rating_method`, the `building_coverage` and `contents_coverage` limits, optional `building_deductible` and `contents_deductible` values, and an optional `is_lender_required` flag. The new policy is recorded against the structure's `property_id`, its `holder_id` is set from the property's owner at quote time, its `status` enters `QUOTED`, and its `quoted_premium` is computed immediately. A claim likewise carries a `status` field that tracks its own lifecycle. The `rating_method` is one of `RISK_RATING_2_0` or `LEGACY_SUBSIDIZED`. Coverage limits are capped: `building_coverage` must lie between 0 and 250000 inclusive and `contents_coverage` between 0 and 100000 inclusive; each deductible must be one of 1000, 2000, 5000, or 10000, with `building_deductible` defaulting to 2000 and `contents_deductible` defaulting to 1000. A request that exceeds a coverage cap or names a deductible outside the permitted set is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED` (HTTP 422). The legacy subsidized regime is available only inside a Special Flood Hazard Area: electing `LEGACY_SUBSIDIZED` for a property whose `is_sfha` is false is rejected with `ERR_RATING_METHOD_NOT_ELIGIBLE` (HTTP 422); the Risk Rating 2.0 regime is available in any zone.

The premium is built in a pinned evaluation order, because the surcharge depends on occupancy, the discount is keyed on the community, and the flat charges are constant — so the risk base is computed first, the community discount is applied next, and the flat amounts are added last. **Step one — risk base.** Under `RISK_RATING_2_0`, the flood zone selects a rate band: zone `VE` maps to the HIGH band, zone `AE` to the MODERATE band, and zone `X` to the LOW band. The applicable building rate is 0.0040 for the HIGH band, 0.0025 for the MODERATE band, and 0.0012 for the LOW band, while the contents rate is 0.0020 regardless of band. The property's freeboard — taken from the latest non-superseded elevation certificate's `freeboard_ft` — selects an elevation factor on a step schedule: a freeboard of at least 3 feet gives 0.70; a freeboard of at least 1 foot but less than 3 feet gives 0.85; a freeboard of at least 0 feet but less than 1 foot gives 1.00; a freeboard of at least −1 foot but less than 0 gives 1.50; and a freeboard below −1 foot gives 2.00. The risk base is the building coverage multiplied by its band rate plus the contents coverage multiplied by the contents rate, that whole sum multiplied by the elevation factor, and then rounded to whole dollars. Under `LEGACY_SUBSIDIZED`, the elevation certificate is ignored entirely; the risk base is the building coverage multiplied by the legacy building rate for the flood zone plus the contents coverage multiplied by the legacy contents rate for the flood zone, rounded to whole dollars, where the legacy building rate is 0.0060 for `AE`, 0.0090 for `VE`, and 0.0010 for `X`, and the legacy contents rate is 0.0035 for `AE`, 0.0050 for `VE`, and 0.0008 for `X`. **Step two — discount.** The discounted subtotal is the risk base multiplied by one minus the community's `crs_discount_pct`, rounded to whole dollars. **Step three — surcharge.** The HFIAA surcharge is 25 dollars when the property's occupancy is `PRIMARY_RESIDENCE` and 250 dollars when it is `NON_PRIMARY`. **Step four — total.** The `quoted_premium` is the discounted subtotal plus a flat increased-cost-of-compliance premium of 75 dollars, plus a flat federal policy fee of 50 dollars, plus the occupancy surcharge. The two regimes will therefore produce different premiums for identical coverage, community, and property inputs.

### 3.5. Binding, the Waiting Period, and Activation

An `Underwriter` binds a policy that is in `QUOTED` status, moving it to `BOUND`. Binding is permitted only while the policy is `QUOTED`; an attempt against any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). Binding requires that the property's community is participating: if the resolved community's `participating` flag is false, the bind is rejected with `ERR_COMMUNITY_NOT_PARTICIPATING` (HTTP 409). The rating-method eligibility rule is re-checked at bind as well as at quote, so binding a `LEGACY_SUBSIDIZED` policy on a non-SFHA property is rejected with `ERR_RATING_METHOD_NOT_ELIGIBLE` (HTTP 422). On a successful bind the system stamps `bind_date` with the current logical-clock instant and derives the coverage dates: the waiting period is 0 days when the policy was written to satisfy a loan closing — that is, when `is_lender_required` is true — and 30 days otherwise, so `effective_date` is the bind date plus the waiting period, and `expiration_date` is the effective date plus 365 days. The coverage window is half-open at its end: a loss exactly at the effective instant is covered, and a loss at or after the expiration instant is not.

A `BOUND` policy becomes `ACTIVE` when an `Underwriter` activates it. Activation is permitted only from `BOUND`; otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409). Activation additionally requires that the waiting period has elapsed — the current logical-clock instant must be at or after the policy's `effective_date`; an earlier attempt is rejected with `ERR_WAITING_PERIOD_NOT_ELAPSED` (HTTP 409). When a policy activates, the property's `active_policy_id` is set to point at it, and where the structure is both in an SFHA and mortgaged the property's `compliance_status` becomes `COMPLIANT`.

An `Underwriter` may also retire a quote that was never bound: a policy in `QUOTED` status can be expired directly, moving it to the terminal `EXPIRED` status; this is permitted only from `QUOTED`, and otherwise yields `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Cancelling, Lapsing, and the Proration of Premium

An `Underwriter` may cancel a policy that is in either `BOUND` or `ACTIVE` status, moving it to the terminal `CANCELLED` status; cancellation from any other status is rejected with `ERR_INVALID_STATE` (HTTP 409), and the request must carry `expected_policy_version` matching the live `version` per §2.6. The financial outcome of cancellation depends on whether coverage had begun. Cancelling a `BOUND` policy — one whose coverage never started — sets `earned_premium` to 0 and leaves the credit balance untouched. Cancelling an `ACTIVE` policy prorates the premium: the term is 365 days, the days elapsed are the whole days from the effective date to the current instant clamped to the range from 0 to the full term, and the `earned_premium` is the quoted premium multiplied by days elapsed divided by the term, rounded to whole dollars. The refund returned to the holder is the quoted premium minus the earned premium, computed as the exact complement so that earned premium plus refund equals the quoted premium. In both cases the property's `active_policy_id` is cleared to null, and where the structure is both SFHA and mortgaged its `compliance_status` cascades to `LAPSED`, because required coverage has been withdrawn.

A policy that has run its full term lapses. An `Underwriter` may lapse a policy that is in `ACTIVE` status — and only `ACTIVE`, otherwise `ERR_INVALID_STATE` (HTTP 409) — but only once the term has run: the current logical-clock instant must be at or after the policy's `expiration_date`, and an earlier attempt is rejected with `ERR_POLICY_NOT_EXPIRED` (HTTP 409). Lapsing moves the policy to the terminal `LAPSED` status, clears the property's `active_policy_id`, and, for a structure that is both SFHA and mortgaged, cascades the property's `compliance_status` to `LAPSED`.

### 3.7. Policy Transfer as an Assumption

When a property changes hands, its `Underwriter` can transfer the in-force policy to the buyer rather than writing a new one. A transfer names the existing `from_policy_id` and the `new_owner_id` of the buyer assuming the policy, and it must carry `expected_policy_version` matching the source policy's live `version` (see §2.6). The source policy must be `ACTIVE`; a transfer against any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). A transfer is an assumption, not a cancellation: there is no cash refund to the old owner, and the unearned premium rides with the policy to the new owner. The source policy moves to the terminal `TRANSFERRED` status, and its premium is prorated exactly as on cancellation — the `earned_premium` is the quoted premium multiplied by days elapsed (clamped to the term) divided by the 365-day term, rounded to whole dollars. The unearned remainder, recorded as the transfer's `credited_amount`, is the quoted premium minus the earned premium, and it is added to the policy's `premium_credit_balance`; earned premium plus credit balance therefore equals the quoted premium. The transfer also stamps an `effective_at` instant from the logical clock, reassigns the policy's `holder_id` and the property's `owner_id` to the new owner, and records `superseded_policy_id` as the source policy's own id, forming the self-referential supersede link from the new arrangement back to the policy it replaces.

### 3.8. Filing and Reviewing Claims

A `PolicyHolder` files a claim under a policy by supplying the `policy_id`, their own `claimant_id` (which must equal the policy's `holder_id`), the `date_of_loss`, and the loss detail: an optional `building_loss` and `contents_loss` (each defaulting to 0, reported at replacement cost), an optional `depreciation_pct` (defaulting to 0, a fraction at least 0 and strictly less than 1 used for actual-cash-value settlement), an optional `substantial_damage` flag (defaulting to false), and an optional `icc_eligible_cost` (defaulting to 0, the reported cost of elevation, demolition, or relocation). A newly filed claim enters the `SUBMITTED` status.

An `Adjuster` opens review on a `SUBMITTED` claim, advancing it to `UNDER_REVIEW`. The transition is permitted only from `SUBMITTED` (otherwise `ERR_INVALID_STATE`, HTTP 409) and requires two coverage checks: the claim's policy must currently be `ACTIVE`, failing which the request is rejected with `ERR_POLICY_NOT_ACTIVE` (HTTP 409); and the `date_of_loss` must fall within the coverage window — at or after the policy's `effective_date` and strictly before its `expiration_date` — so that a loss during the waiting period or on/after expiration is rejected with `ERR_LOSS_OUTSIDE_COVERAGE` (HTTP 409).

### 3.9. The Proof-of-Loss and the Sixty-Day Deadline

A claim under review must be supported by a sworn proof-of-loss before it can be paid. A `PolicyHolder` files a proof-of-loss against a claim by supplying the `claim_id` and the sworn figures: `documented_building_loss` and `documented_contents_loss`, each defaulting to 0. On filing, the system stamps `filed_at` from the logical clock, sets `review_status` to `PENDING`, and computes `days_after_loss` as the whole days between the claim's `date_of_loss` and the filing instant.

An `Adjuster` reviews a pending proof-of-loss and either accepts or rejects it. Acceptance is permitted only when the proof is `PENDING` and the claim it supports is `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`, HTTP 409). Two further conditions guard acceptance. The filing must be timely: the sixty-day deadline is inclusive, so `days_after_loss` must be at most 60 — exactly day 60 is on time and day 61 is late — and a late filing is rejected with `ERR_PROOF_OF_LOSS_LATE` (HTTP 409). The sworn figures must reconcile with the claim: the sum of `documented_building_loss` and `documented_contents_loss` must equal the sum of the claim's `building_loss` and `contents_loss`, and a mismatch is rejected with `ERR_PROOF_OF_LOSS_MISMATCH` (HTTP 422). Acceptance moves the proof's `review_status` to `ACCEPTED`.

Rejection of a pending proof-of-loss moves its `review_status` to `REJECTED` and, when the rejected proof supports a claim that is `UNDER_REVIEW`, bounces that claim back to `SUBMITTED`, advancing the claim's `version` as well. This revision loop lets the claimant file a corrected proof-of-loss while still inside the sixty-day window. Both review actions are performed by an `Adjuster`.

### 3.10. Claim Settlement: Replacement Cost versus Actual Cash Value

An `Adjuster` approves a claim that is `UNDER_REVIEW`, moving it to the terminal `APPROVED` status and computing its payout. Approval has three preconditions, and the request must carry `expected_claim_version` matching the live `version`: the claim must be `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`, HTTP 409); an accepted proof-of-loss must exist for it — a proof whose `review_status` is `ACCEPTED` — failing which the approval is rejected with `ERR_PROOF_OF_LOSS_MISSING` (HTTP 409); and the version must match, failing which it is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412).

The settlement is computed building-and-contents separately, each net of its own deductible, with each bucket rounded before its deductible is subtracted. The building loss is adjusted by occupancy: for a `PRIMARY_RESIDENCE` the building is settled at full replacement cost with no depreciation, so the adjusted building loss equals the reported `building_loss`; for a `NON_PRIMARY` structure the building is depreciated to actual cash value, so the adjusted building loss is the reported `building_loss` multiplied by one minus `depreciation_pct`, rounded to whole dollars — which yields a strictly lower building figure for the same loss. Contents are always settled at actual cash value: the adjusted contents figure is the reported `contents_loss` multiplied by one minus `depreciation_pct`, rounded to whole dollars. The `building_payable` is the smaller of the adjusted building loss and the `building_coverage`, minus the `building_deductible`, with the result floored at 0. The `contents_payable` is the smaller of the adjusted contents figure and the `contents_coverage`, minus the `contents_deductible`, with the result floored at 0.

The increased-cost-of-compliance benefit pays only on a substantially damaged structure. When `substantial_damage` is true, the `icc_payable` is the smaller of the reported `icc_eligible_cost` and the ICC coverage cap of 30000 dollars; when `substantial_damage` is false, no ICC is paid and `icc_payable` is 0 even if an `icc_eligible_cost` was reported — an ICC cost supplied on a non-substantial claim is the condition behind `ERR_ICC_NOT_ELIGIBLE` (HTTP 422). The `settlement_total` is the sum of `building_payable`, `contents_payable`, and `icc_payable`.

On approval the ledger cascade fires: the policy's `total_claims_paid` is increased by the settlement total; the property's `loss_history_count` is increased by one; and if that brings the loss count to 2 or more, the property's `is_repetitive_loss` flag is set to true. An `Adjuster` may instead deny a claim that is `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`, HTTP 409), which also requires `expected_claim_version` to match (otherwise `ERR_STALE_CLAIM_VERSION`, HTTP 412); a denial moves the claim to the terminal `DENIED` status, leaves `settlement_total` at 0, and has no ledger impact.

### 3.11. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed precedence so that the surfaced error is deterministic. Authentication is checked first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Role authorization is checked next: a recognized role not permitted for the operation yields `ERR_FORBIDDEN`. Existence is checked third: every path identifier and body foreign key must resolve, left-to-right, or the request yields `ERR_NOT_FOUND`. Resource ownership for holder-scoped operations is checked fourth, yielding `ERR_NOT_RESOURCE_OWNER` when the acting holder is not the owner/holder/claimant. State correctness for the requested transition is checked fifth, yielding `ERR_INVALID_STATE`. Only after these gates pass are the domain-specific business rules of the operation evaluated — community participation, rating-method eligibility, coverage caps, waiting-period elapse, policy-active and loss-window checks, proof-of-loss timeliness and reconciliation, accepted-proof presence, ICC eligibility — and finally the optimistic-concurrency version match, which carries `ERR_STALE_POLICY_VERSION` or `ERR_STALE_CLAIM_VERSION` as applicable. A malformed body, a wrong type, or a missing required field is rejected with `ERR_VALIDATION` (HTTP 400).

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify an existing resource — including state transitions and the clock-setting capability — return `200 OK`. List and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/communities` | Create an NFIP community with a CRS class | FemaAdmin |
| GET | `/communities/{id}` | Get a community | FemaAdmin, Underwriter, Adjuster, PolicyHolder |
| PATCH | `/communities/{id}` | Update a community's CRS class or participation flag | FemaAdmin |
| GET | `/communities/{id}/properties` | List properties in a community | FemaAdmin, Underwriter, Adjuster |
| POST | `/properties` | Register an insurable property | PolicyHolder, Underwriter |
| GET | `/properties/{id}` | Get a property | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| GET | `/properties` | List properties; filter by owner_id or community_id | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| GET | `/properties/{id}/elevation-certificates` | List elevation certificates for a property | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| GET | `/properties/{id}/policies` | List policies for a property | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| POST | `/elevation-certificates` | File an elevation certificate for a property | PolicyHolder, Underwriter |
| GET | `/elevation-certificates/{id}` | Get an elevation certificate | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| POST | `/properties/{id}/policies` | Quote a flood policy for a property | PolicyHolder, Underwriter |
| GET | `/policies/{id}` | Get a policy | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| POST | `/policies/{id}/bind` | Bind a QUOTED policy | Underwriter |
| POST | `/policies/{id}/expire-quote` | Retire a QUOTED policy never bound | Underwriter |
| POST | `/policies/{id}/activate` | Activate a BOUND policy once the waiting period has elapsed | Underwriter |
| POST | `/policies/{id}/cancel` | Cancel a BOUND or ACTIVE policy | Underwriter |
| POST | `/policies/{id}/lapse` | Lapse an ACTIVE policy whose term has expired | Underwriter |
| POST | `/policy-transfers` | Transfer (assume) an ACTIVE policy to a new owner | Underwriter |
| GET | `/policy-transfers/{id}` | Get a policy transfer record | Underwriter, FemaAdmin, PolicyHolder |
| GET | `/policy-transfers` | List policy transfers; filter by from_policy_id or superseded_policy_id | Underwriter, FemaAdmin |
| POST | `/claims` | File a claim under a policy | PolicyHolder |
| GET | `/claims/{id}` | Get a claim | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| GET | `/claims` | List claims; filter by policy_id | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| POST | `/claims/{id}/open-review` | Move a SUBMITTED claim to UNDER_REVIEW | Adjuster |
| POST | `/claims/{id}/approve` | Approve a claim with an accepted proof-of-loss | Adjuster |
| POST | `/claims/{id}/deny` | Deny a claim under review | Adjuster |
| GET | `/claims/{id}/proofs-of-loss` | List proofs-of-loss for a claim | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| POST | `/proofs-of-loss` | File a sworn proof-of-loss for a claim | PolicyHolder |
| GET | `/proofs-of-loss/{id}` | Get a proof-of-loss | PolicyHolder, Underwriter, Adjuster, FemaAdmin |
| POST | `/proofs-of-loss/{id}/accept` | Accept a proof-of-loss | Adjuster |
| POST | `/proofs-of-loss/{id}/reject` | Reject a proof-of-loss | Adjuster |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to an absolute UTC instant | FemaAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_COMMUNITY_NOT_PARTICIPATING` | 409 |
| `ERR_RATING_METHOD_NOT_ELIGIBLE` | 422 |
| `ERR_COVERAGE_LIMIT_EXCEEDED` | 422 |
| `ERR_WAITING_PERIOD_NOT_ELAPSED` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_LOSS_OUTSIDE_COVERAGE` | 409 |
| `ERR_PROOF_OF_LOSS_LATE` | 409 |
| `ERR_PROOF_OF_LOSS_MISSING` | 409 |
| `ERR_PROOF_OF_LOSS_MISMATCH` | 422 |
| `ERR_ICC_NOT_ELIGIBLE` | 422 |
| `ERR_POLICY_NOT_EXPIRED` | 409 |
| `ERR_STALE_POLICY_VERSION` | 412 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
