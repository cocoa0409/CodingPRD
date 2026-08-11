# Bankruptcy Trustee Claims API — Product Requirements Document

## 1. Introduction

A chapter 7 liquidation moves money through a gauntlet of statutory checkpoints: assets are investigated and sold, proofs of claim are filed and objected to, pre-petition transfers are clawed back from preference recipients, and whatever remains cascades through priority classes under a strict distribution waterfall — all under court supervision, and all reconcilable to the cent. This document specifies the Bankruptcy Trustee Claims API, the system of record for a panel trustee administering that lifecycle end to end: case assignment and asset investigation, claims-register and bar-date administration, claim objection and allowance determination, preference and fraudulent-transfer analysis with demand, asset liquidation through court-approved auction, distribution by priority class, trustee compensation computed under a §326(a)-style tiered commission with court approval, and the final report that closes the case.

Two commitments shape the design. The first is segregation of duties: the `Trustee` administers but cannot approve; the `Court` approves but never files; the `Clerk` opens cases and administers the bar date; a `Creditor` files and may withdraw only its own claim. The second is exact reconciliation: the claims register and the distribution waterfall are two views of the same dollars, and the estate's cash-on-hand ledger must at every instant equal posted receipts minus posted disbursements. All endpoints are mounted under `/trustee`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and invariants that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` specifies their operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `Trustee`, `Clerk`, `Court`, and `Creditor`. A request that is missing either header, or that presents a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). An empty or whitespace-only `X-User-ID` is malformed, and an `X-User-Role` value other than the four recognized roles is likewise malformed rather than merely unpermitted — both surface `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, never `ERR_FORBIDDEN_FOR_ROLE`. A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Identity semantics differ by role, and the difference is contractual. When `X-User-Role` is `Trustee`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as the `trustee_user_id` attribute of the `Case` at case creation, and every trustee-bound mutation on that case then requires the presented `X-User-ID` to equal the stored `trustee_user_id`, failing with `ERR_NOT_ASSIGNED_TRUSTEE` (HTTP 403) on a mismatch. When `X-User-Role` is `Clerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. When `X-User-Role` is `Court`, `X-User-ID` is an opaque operator identifier as well; it is never compared to an entity's `id`, and segregation of duties follows structurally from the role split rather than from any identity comparison. When `X-User-Role` is `Creditor`, `X-User-ID` is the `id` of the acting `Creditor`; ownership checks on any resource that references a `Creditor` compare the resource's foreign-key field to `X-User-ID` — concretely, a creditor may withdraw only a claim whose `creditor_id` equals the presented `X-User-ID`, and a mismatch is rejected with `ERR_NOT_ASSIGNED_TRUSTEE` (HTTP 403).

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` that is not an integer or falls outside 1–100, and an `offset` that is not an integer or is negative, are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Because many records share a creation timestamp, ties are broken by the server's insertion order — the sequence in which the records were accepted.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All temporal reasoning in the system reads a server-maintained logical clock, never the wall clock. At server startup the logical time is exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A Court-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Every temporal gate in the system — the claims bar date comparison at claim filing, the sale and fee `effective_on` windows, the preference lookback windows, and the liquidation gate that requires the bar date to have passed — evaluates against this logical clock. The logical clock also stamps every server-recorded timestamp — `created_at`, `updated_at`, `resolved_at`, `proposed_at`, `sale_approved_on`, the `received_at` of a settlement claim-swap row, and the `api_request_timestamp` of every response envelope — so all of them read the same logical instant until the clock is advanced.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly one with every modification to the resource; a single request that changes several fields — or cascades across several resources — increments each affected resource's version exactly once.

The `FinalReport` is the single exception to this convention: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

Mutations that recompute derived totals on the `Case` — `estate_cash_on_hand_cents` or `allowed_claims_total_cents` — are themselves case mutations: each such recomputation refreshes the case's `updated_at` and increments its `version`, which is what makes the optimistic-concurrency guards of §2.9 meaningful.

### 2.6. Case Posture and Hierarchical Consistency

The `Case` is the root aggregate of the system: every claim, asset, objection, avoidance action, recovery deposit, auction sale, distribution plan, fee application, and the final report belongs to exactly one case through its `case_id`. A case advances through a fixed posture sequence — `OPEN`, then `ASSET_INVESTIGATION`, then `CLAIMS_ADMINISTRATION`, then `LIQUIDATION`, then `DISTRIBUTION`, then `FINAL_REPORT`, and finally `CLOSED`. A second terminal posture, `CONVERTED_DISMISSED`, is reachable from any non-terminal posture when the court converts or dismisses the case.

Once a case reaches `CLOSED` or `CONVERTED_DISMISSED` it is frozen: no case-scoped mutation endpoint may operate on it, and any such attempt is rejected with `ERR_CASE_CLOSED` (HTTP 409). Hierarchical consistency flows the other way as well — transitions on child resources (a sale consummation, a claim allowance, a dividend posting) update the parent's derived totals in the same request, so a PRD reader should treat every cascade described in §3 as atomic within a single call.

### 2.7. The Estate Ledger and Fiscal Sufficiency

Two derived totals on the `Case` form the system's fiscal backbone. The first, `estate_cash_on_hand_cents`, always equals the sum of `net_proceeds_cents` over auction sales whose `proceeds_status` is `POSTED`, plus the sum of `amount_cents` over recovery deposits whose `status` is `POSTED`, minus the sum of `amount_cents` over dividends whose `status` is `POSTED`, minus the sum of `approved_amount_cents` over fee applications whose `status` is `PAID`. The ledger invariant is that this figure never goes negative: any disbursement or compensating void that would drive it below zero is rejected with `ERR_INSUFFICIENT_ESTATE_FUNDS` (HTTP 409). The second total, `allowed_claims_total_cents`, is the sum of `allowed_amount_cents` over all claims of the case currently in `ALLOWED` status, and it rises and falls as claims are allowed, reopened, and resolved.

Fiscal sufficiency gates three distinct operations in §3: paying an approved fee, proposing a distribution plan, and entering the distribution posture. Each is checked against the same invariant family, surfacing as `ERR_INSUFFICIENT_ESTATE_FUNDS` or, where the failing condition is a non-positive distribution pool, `ERR_NO_FUNDS_TO_DISTRIBUTE`.

### 2.8. Monetary Values and Precision

All monetary values in the system are integer cents — no floating-point arithmetic appears anywhere in a calculation. Where a formula divides, it floors toward whole cents: each tier of the trustee commission is truncated to whole cents by integer division before the tiers are summed, and each per-claim waterfall dividend is floored to whole cents with the class remainder assigned to a designated last claim, as §3.6 specifies. Calendar computations (lookback windows, objection windows) use whole-day granularity, while timestamp comparisons such as the late-claim determination compare ISO 8601 instants at second granularity.

### 2.9. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and both guard the `Case` aggregate: confirming a distribution plan, and filing a fee application on a case. Each requires a non-optional `expected_case_version` field in the request body, carrying the client’s last observed `version` of the parent case. If the case's current `version` has advanced beyond that value — because a sale was consummated, a claim was allowed, a dividend was posted, or any other mutation bumped it — the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). This prevents a client from confirming a plan whose waterfall snapshot, or filing a fee whose commission basis, was computed against a case state the client has not observed. Endpoints not named here take no version field at all.

### 2.10. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers, the server validates existence sequentially from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource — for example, a request targeting a claim under a non-existent case fails on the case identifier before the claim identifier is ever examined. The same left-to-right discipline applies to creation operations under a parent collection. Requests to paths the API does not define — including unsupported methods on defined paths — are likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.11. Validation Ordering

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the earliest failing tier determines the error surfaced:

1. Header presence and well-formedness, on every endpoint — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role permission for the endpoint, on every endpoint — `ERR_FORBIDDEN_FOR_ROLE`.
3. Left-to-right existence of every path identifier — `ERR_NOT_FOUND`.
4. The case terminal-state guard, on all case-scoped mutation endpoints — `ERR_CASE_CLOSED`.
5. From-state validity for the requested transition — `ERR_INVALID_STATE`.
6. Segregation-of-duties identity binding (the assigned-trustee match and the creditor self-service match) — `ERR_NOT_ASSIGNED_TRUSTEE`.
7. Temporal gates: the liquidation gate requires the logical clock to be strictly past the bar date (`ERR_BAR_DATE_NOT_PASSED`), sale consummation requires the clock to be at or past `effective_on` (`ERR_OBJECTION_WINDOW_OPEN`), and fee payment requires the clock to be at or past `effective_on` (`ERR_FEE_NOT_YET_EFFECTIVE`).
8. Referential integrity within the case boundary: a `SECURED` claim must name an existing asset of the same case, an objection must name a claim of the case, a sale must name an asset of the case, and a recovery deposit must name an avoidance action of the case — `ERR_REFERENTIAL_INTEGRITY`.
9. Uniqueness: `case_number` unique across all cases, `creditor_ref` unique across all creditors, at most one `PENDING` objection per claim, and at most one `PROPOSED` or `APPROVED` sale per asset — `ERR_DUPLICATE`, with the two per-resource guards surfaced at their workflow sites as `ERR_OBJECTION_ALREADY_PENDING` and `ERR_SALE_ALREADY_PENDING`.
10. Amount shape: a demanded amount within its allowed band, a partial settlement strictly below the filed amount, an approved fee no greater than requested, and a hammer price passing the minimum-price floor — the `ERR_INVALID_AMOUNT` category, surfaced at the workflow sites as `ERR_INVALID_DEMAND_AMOUNT`, `ERR_SETTLEMENT_NOT_PARTIAL`, `ERR_APPROVAL_EXCEEDS_REQUEST`, and `ERR_BELOW_MINIMUM_PRICE`.
11. Posture-entry integrity at the liquidation and distribution gates: at the distribution gate the pending-asset check (`ERR_ASSETS_PENDING_SALE`) runs first and the objected-register check (`ERR_OBJECTIONS_PENDING`) runs second; at the liquidation gate the unreviewed-claims check (`ERR_CLAIMS_UNREVIEWED`) runs immediately after the tier-7 bar-date check.
12. Fiscal sufficiency per §2.7 — `ERR_INSUFFICIENT_ESTATE_FUNDS`, with `ERR_NO_FUNDS_TO_DISTRIBUTE` where the failing condition is a non-positive pool.
13. Request-body well-formedness — `ERR_INVALID_REQUEST` — is evaluated last of all: required fields present, types correct, amounts non-negative, enum members valid, and conditionally required fields supplied (a claim whose `priority_class` is `SECURED` must carry `secured_by_asset_id`).

## 3. Business Logic & Workflows

### 3.1. Case Intake, Trustee Assignment, and the No-Asset Exit

A `Clerk` opens a bankruptcy case by supplying the court docket number as `case_number` (unique across all cases; a collision is rejected with `ERR_DUPLICATE`), the debtor's full legal name as `debtor_name`, the petition filing date as `filed_on` (the anchor from which every preference lookback window is measured), the federal judicial district code as `district`, and the `trustee_user_id` of the panel trustee being assigned. Two optional inputs complete intake: `scheduled_unsecured_total_cents`, the debtor-scheduled general unsecured total (defaulting to 0 and purely informational — it never gates claim administration), and `objection_window_days`, the number of days a sale order or fee approval must sit before becoming effective under the court's local rule (defaulting to 30 days). A new case begins in `OPEN` posture with `bar_date_noticed` false, `no_asset_report_filed` false, and both derived totals at zero.

From `OPEN`, the assigned trustee begins asset investigation, moving the case to `ASSET_INVESTIGATION`. This requires the presenter to be the case's assigned trustee (otherwise `ERR_NOT_ASSIGNED_TRUSTEE`) and requires at least one asset row to exist for the case — a trustee who begins investigation with nothing scheduled is rejected with `ERR_NO_ASSETS_SCHEDULED`, unless the estate is instead closed through the no-asset path described next.

When the trustee determines there is nothing to administer, filing a no-asset report moves the case directly from `OPEN` to `CLOSED`. The path is available only when no asset rows exist for the case, no claim exists in any of `FILED`, `UNDER_REVIEW`, `OBJECTED`, or `ALLOWED` status, and `estate_cash_on_hand_cents` is exactly zero; each of these preconditions surfaces `ERR_INVALID_STATE` (HTTP 409) when it fails. Filing sets `no_asset_report_filed` to true and closes the case, incrementing the case's `version` once.

At any point before termination, the `Court` may convert or dismiss the case, moving it from any non-terminal posture to `CONVERTED_DISMISSED`. The one obstruction is a plan in flight: conversion is rejected with `ERR_PLAN_EXECUTING` while any distribution plan of the case is `EXECUTING`. Conversion cascades atomically through the aggregate — every claim in `FILED`, `UNDER_REVIEW`, or `OBJECTED` becomes `WITHDRAWN`; every asset in `SCHEDULED`, `UNDER_INVESTIGATION`, `MARKED_FOR_SALE`, or `IN_AUCTION` becomes `ABANDONED`; and every avoidance action not already in `RESCINDED`, `ABANDONED`, `SETTLED`, or `JUDGMENT` becomes `ABANDONED` — and the case's `version` increments. Each swept claim's `objection_id` clears to null, while the objection rows themselves are left untouched — a `PENDING` objection survives conversion in place.

### 3.2. Creditor Registration, the Bar Date, and Claims Intake

Before any claim can be filed, a `Clerk` registers each creditor with its `legal_name`, a unique external reference `creditor_ref` (duplicates rejected with `ERR_DUPLICATE`), a service `contact_email`, and the `insider` flag (defaulting to false) that marks a §101(31) insider of the debtor and drives the longer one-year preference lookback described in §3.5.

Setting the claims bar date is the `Clerk`'s pivotal administrative act. The supplied `bar_date` must be strictly after the case's `filed_on`; a bar date on or before the petition date is rejected with `ERR_INVALID_BAR_DATE` (HTTP 422). When the bar date is accepted, four things happen atomically: `claim_bar_date` is recorded on the case, `bar_date_noticed` flips to true (the §341/bar-date notice to scheduled creditors has issued), the case advances from `ASSET_INVESTIGATION` to `CLAIMS_ADMINISTRATION`, and every asset still `SCHEDULED` is swept to `UNDER_INVESTIGATION`. The case's `version` increments.

Proofs of claim arrive through two channels: a `Creditor` files its own claim, or the `Clerk` files on a creditor's behalf at intake. For a `Creditor` filing, the payload's `creditor_id` must equal the presented `X-User-ID` — a mismatch is rejected with `ERR_NOT_ASSIGNED_TRUSTEE` (HTTP 403) — and in either channel the `creditor_id` must name an existing creditor, else `ERR_REFERENTIAL_INTEGRITY` (HTTP 422). The filing payload carries the `creditor_id`, the clerk-stamped `received_at` timestamp, the asserted face amount `filed_amount_cents`, and the asserted `priority_class` — one of `SECURED`, `PRIORITY_TAX`, `PRIORITY_WAGE`, `PRIORITY_CONSUMER`, or `GENERAL_UNSECURED`. A claim in the `SECURED` class must also carry `secured_by_asset_id` naming the encumbering asset; omitting it is a malformed-body rejection (`ERR_INVALID_REQUEST`), and naming an asset that does not exist or belongs to a different case is a referential rejection (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422).

Two system-computed attributes complete the register entry. The `claim_number` is the claim's 1-based position in the case's register, ordered by `received_at`, with ties broken first by the creditor's `created_at`, then by the claim's own `created_at`, and finally by server insertion order. The register is re-ranked on every filing — a newly filed claim whose `received_at` predates existing entries takes a lower `claim_number` and shifts the later-received claims up — and this renumbering updates only the `claim_number` fields, refreshing neither `updated_at` nor `version` of the shifted claims. The `late` flag is false while the case's `claim_bar_date` is null (no bar date yet — everything is timely); once a bar date exists, a claim is late exactly when its `received_at` is strictly after `claim_bar_date` — a claim received at the precise bar-date instant is timely, because the comparison is strictly-greater. Every claim enters the register in `FILED` status. Where a claim is later re-noticed under a new class, the superseding claim records its predecessor in `reclassified_from_claim_id` (null when the claim supersedes nothing).

The claims register is browsable per case with optional filters `status`, `priority_class`, `late`, and `creditor_id`; the `late` filter accepts the case-insensitive values `true` and `false`, and any other value applies no late filtering. A cross-case claim search supports foreign-key reverse lookup by `creditor_id`, `secured_by_asset_id`, `objection_id`, and `reclassified_from_claim_id`. From a claim one can also list the dividends paid against it, the objections filed against it, and — for a secured claim — the assets encumbered by it, reported as the union of the assets whose `encumbered_claim_id` names the claim and the asset named by the claim's own `secured_by_asset_id`.

### 3.3. Claim Review, Objection, and the Reconsideration Cycle

Review begins when the `Trustee` moves a claim from `FILED` to `UNDER_REVIEW`; the transition carries no further preconditions.

Allowance is the trustee's determination that the claim stands as filed: an `UNDER_REVIEW` claim becomes `ALLOWED`, its `allowed_amount_cents` is set equal to its `filed_amount_cents`, and the case's `allowed_claims_total_cents` increases by that amount, with the case `version` bumping accordingly.

Objection is the trustee's attack on the claim. The trustee objects by supplying the `grounds` — one of `DUPLICATE`, `INSUFFICIENT_DOCUMENTATION`, `AMOUNT_DISPUTED`, `WRONG_CLASS`, `LATE_FILED`, or `NOT_OWED` — together with a `proposed_allowed_amount_cents` (zero asserts full disallowance) and a `proposed_priority_class`. The proposed class must equal the claim's current class unless the grounds are `WRONG_CLASS`; a violation is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Two guards protect the register: the claim must currently be `UNDER_REVIEW` (else `ERR_INVALID_STATE`), and no other objection may already be `PENDING` against the claim (else `ERR_OBJECTION_ALREADY_PENDING`). A successful objection moves the claim to `OBJECTED`, points the claim's `objection_id` at the newly created objection (which itself begins in `PENDING`), and increments the case `version`. If the claim had previously been allowed and then reopened, its prior allowed amount is subtracted from `allowed_claims_total_cents` before it enters `OBJECTED`, so the register total never double-counts a claim under reconsideration. The objection must name a claim of the same case, else `ERR_REFERENTIAL_INTEGRITY`.

Resolution takes four paths, and each stamps the objection's `resolved_at` timestamp:

- The `Court` sustains the objection — permitted while the objection is `PENDING` and the claim is `OBJECTED` with its `objection_id` pointing at this objection. The objection becomes `SUSTAINED`, the claim becomes `DISALLOWED` with `allowed_amount_cents` zeroed, and the claim's `objection_id` clears to null.
- The `Court` overrules the objection — permitted while the objection is `PENDING`. The objection becomes `OVERRULED`, the claim becomes `ALLOWED` as filed (its `allowed_amount_cents` set to `filed_amount_cents`, its `priority_class` unchanged), `allowed_claims_total_cents` increases by the allowed amount, and the claim's `objection_id` clears to null.
- The `Trustee` settles the objection by supplying an `outcome` of `ALLOW`, `DISALLOW`, or `PARTIAL`. An `ALLOW` outcome resolves the claim as `ALLOWED` as filed; a `DISALLOW` outcome resolves it as `DISALLOWED`; a `PARTIAL` outcome resolves it as `ALLOWED` at the supplied `settled_amount_cents` and `settled_priority_class`. For a `PARTIAL` outcome, `settled_priority_class` is optional — when omitted the claim keeps its current class — and `settled_amount_cents` must be a non-negative integer, with a missing, non-integer, or negative value rejected as `ERR_INVALID_REQUEST` (HTTP 400). A partial settlement must name a `settled_amount_cents` strictly less than the claim's `filed_amount_cents` — anything at or above the filed amount is rejected with `ERR_SETTLEMENT_NOT_PARTIAL` (HTTP 422). Where the settlement changes the claim's class, `allowed_claims_total_cents` reflects the new amount only, never a stale residue under the old class. The objection becomes `SETTLED`.
- The `Trustee` withdraws the objection while it is `PENDING`: the objection becomes `WITHDRAWN`, the claim returns to `UNDER_REVIEW` (review restarts), and the claim's `objection_id` clears to null.

Each objection-resolution path increments the case `version`.

Reconsideration closes the loop. The trustee may reopen an `ALLOWED` claim, returning it to `UNDER_REVIEW`, but only while the case is in `CLAIMS_ADMINISTRATION` or `LIQUIDATION` — in any other non-terminal posture (including `OPEN`, `ASSET_INVESTIGATION`, `DISTRIBUTION`, and `FINAL_REPORT`) the register is not open to reconsideration and reopening is rejected with `ERR_CASE_BEYOND_REOPEN` — and only while no `POSTED` dividend references the claim (else `ERR_DIVIDEND_POSTED`). Reopening subtracts the claim's prior `allowed_amount_cents` from `allowed_claims_total_cents` and zeroes the claim's `allowed_amount_cents`. This `ALLOWED` → `UNDER_REVIEW` → `OBJECTED` → `ALLOWED` cycle is what drives successive reconsideration rounds.

A creditor may also withdraw its own claim. From `FILED`, withdrawal requires the presented `X-User-ID` to equal the claim's `creditor_id` (else `ERR_NOT_ASSIGNED_TRUSTEE`) and requires that no `POSTED` dividend reference the claim (else `ERR_DIVIDEND_POSTED`). From `UNDER_REVIEW`, the same identity match is required. Either path leaves the claim terminally `WITHDRAWN`.

### 3.4. Asset Investigation, Exemption, and Court-Supervised Liquidation

Assets enter the system when the `Trustee` (during investigation) or the `Clerk` (at schedule intake) schedules one with a `description`, the `scheduled_value_cents` per the debtor's schedules, an optional `exempt` flag (defaulting to false — exempt assets may not be liquidated), and an optional `encumbered_claim_id` naming the `SECURED` claim that encumbers the asset. Scheduling is not posture-gated — any non-terminal case accepts a new asset — and a supplied `encumbered_claim_id` must name an existing claim of the same case (else `ERR_REFERENTIAL_INTEGRITY`, HTTP 422), though the named claim's priority class is not validated. A newly scheduled asset is `SCHEDULED`. The trustee can open an investigation on it, moving it to `UNDER_INVESTIGATION`; the same sweep happens automatically to every `SCHEDULED` asset when the bar date is set (§3.2).

Marking an asset for sale moves it from `UNDER_INVESTIGATION` to `MARKED_FOR_SALE` and is guarded twice: an asset whose `exempt` flag is true is rejected with `ERR_ASSET_EXEMPT`, and the case must be in `CLAIMS_ADMINISTRATION` or `LIQUIDATION` posture — a case in any other posture is rejected with `ERR_INVALID_STATE` (HTTP 409). The trustee may abandon an asset back to the debtor: from `UNDER_INVESTIGATION` the abandonment carries the standing guard that no `POSTED` dividend may ever reference the asset's proceeds — a condition trivially satisfied before any sale — and from `MARKED_FOR_SALE` no further preconditions apply; either path leaves the asset terminally `ABANDONED`. The `Court`, for its part, may release an exempt asset, moving it from `SCHEDULED` or from `UNDER_INVESTIGATION` to `EXEMPT_RELEASED`, but only when the asset's `exempt` flag is true — releasing an asset whose flag is false is rejected with `ERR_INVALID_STATE` (HTTP 409).

Liquidation proceeds through court-supervised auction. The trustee proposes a sale of a `MARKED_FOR_SALE` asset with a payload naming the `asset_id` (exactly one asset per sale), the winning bidder's `buyer_name`, the gross winning bid `hammer_price_cents`, and the auctioneer and carrier `sale_costs_cents` chargeable to the sale. The named asset must belong to the case (else `ERR_REFERENTIAL_INTEGRITY`), and no other sale of the same asset may be sitting in `PROPOSED` or `APPROVED` (else `ERR_SALE_ALREADY_PENDING`). A proposed sale starts in `PROPOSED` status with `proceeds_status` of `PENDING`, its `net_proceeds_cents` computed as the hammer price minus the sale costs (never permitted to be negative — a proposal whose `sale_costs_cents` exceed its `hammer_price_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), and the asset moves to `IN_AUCTION` in the same request.

Court approval applies the minimum-price gate: the hammer price must be at least the greater of two floors — the sale's own `sale_costs_cents`, and one half of the asset's `scheduled_value_cents` truncated down to whole cents. A hammer price exactly equal to that greater floor is acceptable; anything below is rejected with `ERR_BELOW_MINIMUM_PRICE` (HTTP 422). Approval stamps `sale_approved_on` with the current logical timestamp and computes `effective_on` as that exact instant plus the case's `objection_window_days` days — the objection window during which the order sits before becoming effective. The case `version` increments.

Consummation is the trustee's act of posting the proceeds, permitted only once the logical clock is at or past `effective_on` — earlier attempts are rejected with `ERR_OBJECTION_WINDOW_OPEN`. Consummating an `APPROVED` sale flips its `proceeds_status` to `POSTED` and its status to `CONSUMMATED`, credits `net_proceeds_cents` into `estate_cash_on_hand_cents`, and moves the asset to `SOLD` with its `realized_proceeds_cents` set to the sale's net proceeds. When the sold asset's `encumbered_claim_id` is set and that claim is `ALLOWED`, a secured carve-out is marked for the waterfall of §3.6, capping the secured class's need at the realized proceeds. The case `version` increments.

Cancellation unwinds the auction without touching the ledger. A `PROPOSED` sale may be cancelled by the `Trustee` or the `Court` with no further preconditions. An `APPROVED` sale may be cancelled only by the `Court` — a `Trustee` attempting it is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403) — and only while the logical clock is still before `effective_on` — on or after the effective date the window has closed and cancellation is rejected with `ERR_OBJECTION_WINDOW_CLOSED`. Either path moves the sale to its terminal `CANCELLED` status and returns the asset from `IN_AUCTION` to `MARKED_FOR_SALE`.

Two trustee posture gates frame the liquidation phase. Beginning liquidation moves the case from `CLAIMS_ADMINISTRATION` to `LIQUIDATION` and requires the logical clock to be strictly past `claim_bar_date` (else `ERR_BAR_DATE_NOT_PASSED`) and every claim — timely or late — to have moved at least to `UNDER_REVIEW`, with any claim still `FILED` rejected as `ERR_CLAIMS_UNREVIEWED`. Beginning distribution moves the case from `LIQUIDATION` to `DISTRIBUTION` and requires no asset still in `MARKED_FOR_SALE` or `IN_AUCTION` (else `ERR_ASSETS_PENDING_SALE`), no claim still `OBJECTED` (else `ERR_OBJECTIONS_PENDING`), and a strictly positive `estate_cash_on_hand_cents` (else `ERR_NO_FUNDS_TO_DISTRIBUTE`). Each gate increments the case `version` on success.

### 3.5. Preference and Fraudulent-Transfer Recovery

A trustee who spots an avoidable pre-petition transfer registers an avoidance action with a payload naming the `transferee_creditor_id`, the `transfer_date` on which the transfer occurred, the `transfer_amount_cents`, the `action_type` — either `PREFERENCE_547` or `FRAUDULENT_548` — and a `demand_amount_cents` (which may be less than the full transfer amount). Registration is not posture-gated beyond the case being open; the `transferee_creditor_id` must name an existing creditor (else `ERR_REFERENTIAL_INTEGRITY`, HTTP 422), and at registration `demand_amount_cents` is validated only as a non-negative integer — the band of §3.5's demand step is enforced later, at the demand transition. The server computes two attributes at registration. The `lookback_window_days` is 90 days for a preference action against a non-insider transferee, a full 365 days — one year — for a preference action against a transferee whose `insider` flag is true, and 730 days — two years — for a fraudulent-transfer action. The `avoidable` flag is true exactly when the `transfer_date` falls on or after the petition date minus the lookback window and strictly before the petition date itself: a transfer dated precisely at the earliest window boundary is avoidable, while a transfer dated precisely on `filed_on` is post-petition and not avoidable. All of these date computations run at whole-day granularity. A new action begins `IDENTIFIED`. Case-scoped action listings accept the filters `status` and `transferee_creditor_id`, and the recovery deposits posted against an action are listable from the action itself.

Analysis gates the action on avoidability: moving from `IDENTIFIED` to `ANALYZED` requires `avoidable` to be true, and an action whose transfer falls outside its lookback window is rejected with `ERR_TRANSFER_NOT_AVOIDABLE`.

Demanding payment moves the action from `ANALYZED` to `DEMANDED` and validates the recorded `demand_amount_cents`: it must be strictly greater than zero and no greater than `transfer_amount_cents` — anything outside that band is rejected with `ERR_INVALID_DEMAND_AMOUNT` (HTTP 422).

Settlement and judgment are the two recovery paths, and each posts its recovery deposit atomically in the same request. When the trustee settles a `DEMANDED` action, the supplied `settled_amount_cents` must be a non-negative integer no greater than the demanded amount — a missing, non-integer, negative, or excessive value is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a zero settlement is accepted, posting a zero-amount deposit; a recovery deposit of exactly `settled_amount_cents` posts in `POSTED` status, the action's `recovered_amount_cents` becomes the settled amount, and `estate_cash_on_hand_cents` increases by that amount. Settlement also performs the claim-swap: if the transfer amount exceeds the settled amount, a compensating claim of `priority_class` `GENERAL_UNSECURED` is created for the transferee creditor in the positive difference, stamped with a `received_at` of the current logical time — recovered dollars reduce the estate's liability to the preference recipient. When the `Court` instead enters judgment on a `DEMANDED` action, a recovery deposit for the full `demand_amount_cents` posts atomically, `recovered_amount_cents` becomes the demanded amount, and the estate cash increases by the demanded amount. The action ends `SETTLED` or `JUDGMENT` respectively, and each path increments the case `version`.

Rescission is the ledger's compensating entry. The `Court` may rescind a `JUDGMENT` action only while the case is not in `DISTRIBUTION` and no plan of the case is `CONFIRMED` or `EXECUTING` — otherwise the distribution machinery is relying on the recovery and rescission is rejected with `ERR_PLAN_RELIES_ON_RECOVERY`. Rescinding flips the linked recovery deposit to `VOIDED`, zeroes the action's `recovered_amount_cents`, and debits `estate_cash_on_hand_cents` by the formerly recovered `demand_amount_cents`, preserving the invariant that cash always equals receipts minus disbursements; the case `version` increments. A trustee may also abandon an action outright from `IDENTIFIED` or `ANALYZED`, leaving it terminally `ABANDONED` with no ledger effect.

Recovery deposits themselves are simple ledger rows: each carries the `avoidance_action_id` it credits, an `amount_cents`, and a `status` of `POSTED` or `VOIDED`. The case-level deposit listing accepts the filters `status` and `avoidance_action_id`, and a deposit that names an action of a different case is a referential violation (`ERR_REFERENTIAL_INTEGRITY`).

### 3.6. Distribution Plans and the Priority Waterfall

With the case in `DISTRIBUTION`, the trustee proposes a distribution plan; proposing while the case is in any other posture is rejected with `ERR_CASE_NOT_IN_DISTRIBUTION` (HTTP 409). Proposal takes no request body; the server snapshots two figures at the proposal instant. The `reserve_for_objected_cents` is a single total: the sum of `filed_amount_cents` over all claims then sitting in `OBJECTED`, aggregated across priority classes — objected claims do not block a proposal; they size the reserve that keeps their dollars out of the pool. The `distributable_cents` is the case's `estate_cash_on_hand_cents` minus the total reserve across classes minus the approved amounts of any fee applications approved but not yet paid; a pool that is not strictly positive is rejected with `ERR_NO_FUNDS_TO_DISTRIBUTE`. The plan records its `plan_sequence` (the count of the case's existing plans — of any status, including `VACATED` — plus one) and its `proposed_at` timestamp, and begins in `PROPOSED` status. Plans of a case are listable with the `status` filter.

Confirmation is the `Court`'s act, and it is where the waterfall actually runs. Confirming a plan requires the case to be in `DISTRIBUTION` (else `ERR_CASE_NOT_IN_DISTRIBUTION`), requires that no other plan of the case be `CONFIRMED` or `EXECUTING` (else `ERR_PLAN_ALREADY_ACTIVE`), and carries the optimistic-concurrency guard of §2.9 — the request must present an `expected_case_version` matching the case's current `version`, and a mismatch is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). On confirmation the case `version` increments, the plan becomes `CONFIRMED`, the per-class `PlanClassAllocation` rows are computed with their `allocated_cents`, and every `Dividend` row is materialized in `COMPUTED` status — the dividend amounts are server-computed at confirmation, never client-supplied.

The waterfall itself proceeds in four steps. First the reserve: for each class, the reserve is the sum of `filed_amount_cents` over `OBJECTED` claims in that class. Second the pool: estate cash on hand, minus the summed reserve, minus the approved-but-unpaid fee amounts, and the pool must be strictly positive. Third the class cascade, in the fixed statutory order `SECURED` → `PRIORITY_TAX` → `PRIORITY_WAGE` → `PRIORITY_CONSUMER` → `GENERAL_UNSECURED`: each class's need is the sum of `allowed_amount_cents` over its `ALLOWED` claims — except that a secured claim's need is capped at the `realized_proceeds_cents` of its securing asset, and any unsecured deficiency spills into `GENERAL_UNSECURED` as a deficiency share on the same claim, so the claim participates in both classes with split amounts — and each class's grant is the lesser of its need and the remaining pool, with the pool reduced by each grant in turn. Fourth the per-claim pro-rata split: if a class's grant equals its need, every claim in the class receives its full `allowed_amount_cents`; otherwise each claim's dividend is its allowed amount multiplied by the class grant and divided by the class need, floored to whole cents — for every claim except the last one in the class's ordering, which is pinned by `claim_number` ascending (with server insertion order as the final tie-break) and never by `id`; that last claim receives the class grant minus the sum of the previously computed dividends, so the class total matches the grant exactly. `PlanClassAllocation` rows are created only for classes whose grant is strictly positive — a class granted nothing leaves no allocation row behind. The computation runs at confirmation time, not at proposal: a claim allowed after proposal but before confirmation enters the computation, while `OBJECTED` claims are excluded from dividends and drive only the reserve.

Execution turns computed dividends into paid ones. Posting a `COMPUTED` dividend flips it to `POSTED`, debits its `amount_cents` from `estate_cash_on_hand_cents`, and credits the same amount into its allocation's `paid_total_cents`; the first posting moves the plan automatically from `CONFIRMED` to `EXECUTING`, and when every dividend of the plan is `POSTED` or `VOIDED` and the paid total equals the allocated amount less the voided remainder, the plan becomes `FULLY_DISTRIBUTED`. Voiding a `COMPUTED` dividend — for a check never claimed — flips it to `VOIDED` and leaves its amount in the estate as unclaimed funds. Voiding alone never starts execution: a plan whose dividends are all voided without any posting remains `CONFIRMED`, and a plan confirmed with no dividend rows at all (every class need zero) likewise stays `CONFIRMED`, until vacated. Each posting or voiding increments the case `version`. Dividends of a plan are listable with the filters `status` and `claim_id`, class allocations are listable per plan, and a case-level allocation listing exposes every plan's `PlanClassAllocation` rows — each of which carries its `plan_id`, its denormalized `case_id`, its `priority_class`, its `allocated_cents`, and its running `paid_total_cents`.

The `Court` may unwind a confirmed plan by vacating it, but only while no dividend of the plan is `POSTED` — a posted dividend makes vacatur impossible (`ERR_DIVIDEND_POSTED`). Vacating flips every dividend of the plan to `VOIDED`, moves the plan to `VACATED`, and increments the case `version`.

When the case's last active plan reaches `FULLY_DISTRIBUTED` — meaning no other plan of the case remains in `PROPOSED`, `CONFIRMED`, or `EXECUTING` — the case moves automatically from `DISTRIBUTION` into the `FINAL_REPORT` posture, and any estate cash still on hand is definitionally unclaimed funds.

### 3.7. Trustee Compensation and Professional Fee Applications

Fee applications are filed by the `Trustee` for its own commission, or by the `Trustee` or `Clerk` at intake on behalf of other professionals. The filing payload names the `applicant_role` — `TRUSTEE`, `AUCTIONEER`, or `COUNSEL` — and the `requested_amount_cents`, and it carries the optimistic-concurrency guard of §2.9: a non-optional `expected_case_version` matching the case's current `version`, with mismatches rejected as `ERR_STALE_CASE_VERSION` (HTTP 412), since an intervening plan confirmation or dividend posting changes the disbursement basis the commission was computed from. When the applicant is the trustee, a `commission_basis` of `DISBURSED` or `PROPOSED` is required, the server computes `computed_commission_cents` on the named basis, and the `requested_amount_cents` must equal the §326 commission computed on the `DISBURSED` basis at the filing instant — a missing `commission_basis` or a mismatched `requested_amount_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). For non-trustee applicants `commission_basis` is optional and `computed_commission_cents` is null. Filing increments the case `version`; a new application begins in `FILED` status. Fee applications of a case are listable with the filters `status` and `applicant_role`.

The §326(a)-style commission runs in four tiers against a basis B expressed in cents: 25 percent of the first $5,000 (the first 500,000 cents), then 10 percent of the next $45,000 (up to 4,500,000 cents beyond the first tier), then 5 percent of the next $950,000 (up to 95,000,000 cents beyond the second tier), then 3 percent of everything above $1,000,000 (100,000,000 cents) of basis. Each tier is truncated down to whole cents by integer division before the tiers are summed — the per-tier floor first, the summation second, in that pinned order.

The basis B depends on the chosen variant. Under `DISBURSED`, B is the sum of the `amount_cents` of all `POSTED` dividends plus the approved amounts of all `PAID` non-trustee fee applications at the filing instant — moneys actually disbursed to parties in interest, excluding the trustee's own compensation. Under `PROPOSED`, B is the sum of `allocated_cents` across the class allocations of the case's `CONFIRMED` plan — amounts proposed to be disbursed under the pending plan — which yields a higher commission earlier in the case than `DISBURSED` when dividends are not yet posted. The status match is strict: only a plan sitting in `CONFIRMED` status at the filing instant contributes, so once the first dividend posting moves the plan to `EXECUTING` (§3.6) its allocations stop counting toward B, and when no plan of the case is `CONFIRMED` the `PROPOSED` basis is zero.

Approval belongs to the `Court` alone, so the filer can never approve its own application — segregation of duties is structural here. The court approves with an `approved_amount_cents` no greater than the `requested_amount_cents`; anything above the request is rejected with `ERR_APPROVAL_EXCEEDS_REQUEST` (HTTP 422). Approval computes `effective_on` as the approval date plus the case's `objection_window_days` days, mirroring the sale-order window. The court may instead deny the application outright, moving it from `FILED` to terminally `DENIED`. Both rulings increment the case `version`.

Payment is the trustee's disbursement of an approved fee, permitted only once the logical clock is at or past the application's `effective_on` (earlier attempts are rejected with `ERR_FEE_NOT_YET_EFFECTIVE`) and only while `estate_cash_on_hand_cents` covers the `approved_amount_cents` (else `ERR_INSUFFICIENT_ESTATE_FUNDS`). Payment moves the application from `APPROVED` to `PAID`, debits the approved amount from the estate cash, and increments the case `version`.

### 3.8. The Final Report and Case Closing

Entry into the `FINAL_REPORT` posture creates the case's final report automatically, in `DRAFT` status, with its four totals computed from the terminal ledger: `total_receipts_cents` is the sum of `POSTED` sale net proceeds plus the sum of `POSTED` recovery deposits; `total_dividends_cents` is the sum of `POSTED` dividends; `total_fees_cents` is the sum of the approved amounts of `PAID` fee applications; and `unclaimed_funds_cents` is receipts minus dividends minus fees — which by the ledger invariant equals the case's `estate_cash_on_hand_cents` at report time, the amount to be remitted to the court registry.

The trustee then files the draft, moving it from `DRAFT` to `FILED`. Filing requires the case to be in `FINAL_REPORT` posture and requires a clean ledger: every fee application of the case in `PAID` or `DENIED` and every dividend in `POSTED` or `VOIDED` — otherwise the filing is rejected with `ERR_FINAL_REPORT_NOT_READY`.

Court approval is the closing act. Approving a report requires it to be in `FILED` status and again requires every fee application of the case to be in `PAID` or `DENIED`. Approval moves the report to `APPROVED` and the case to `CLOSED`, and remits the unclaimed funds: `estate_cash_on_hand_cents` goes to zero. Because a case has at most one final report, the report retrieval returns an array of length zero or one — empty before the `FINAL_REPORT` posture is reached.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection (opening a case, registering a creditor, filing a claim, objecting, scheduling an asset, proposing a sale, registering an avoidance action, proposing a plan, filing a fee application) return `201 Created`. Operations that modify an existing resource — every state transition, approval, posting, and the clock advance — return `200 OK`, as do all reads.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/trustee/_clock/set_current_utc` | Advance the test-driving logical clock | Court |
| POST | `/trustee/cases` | Create a bankruptcy case and assign the panel trustee | Clerk |
| GET | `/trustee/cases` | List cases (filters: `status`, `trustee_user_id`) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/cases/{id}` | Get a case | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/cases/{id}/begin_investigation` | Move a case from `OPEN` to `ASSET_INVESTIGATION` | Trustee |
| POST | `/trustee/cases/{id}/set_bar_date` | Set the claims bar date; enter `CLAIMS_ADMINISTRATION` and sweep scheduled assets | Clerk |
| POST | `/trustee/cases/{id}/begin_liquidation` | Move a case from `CLAIMS_ADMINISTRATION` to `LIQUIDATION` | Trustee |
| POST | `/trustee/cases/{id}/begin_distribution` | Move a case from `LIQUIDATION` to `DISTRIBUTION` | Trustee |
| POST | `/trustee/cases/{id}/file_no_asset_report` | File a no-asset report; move `OPEN` to `CLOSED` | Trustee |
| POST | `/trustee/cases/{id}/convert_or_dismiss` | Convert or dismiss the case from any non-terminal posture | Court |
| POST | `/trustee/creditors` | Register a creditor | Clerk |
| GET | `/trustee/creditors/{id}` | Get a creditor | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/creditors/{id}/avoidance_actions` | List avoidance actions naming this creditor as transferee | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/cases/{id}/claims` | File a proof of claim; assigns `claim_number`; computes the `late` flag | Creditor, Clerk |
| GET | `/trustee/cases/{id}/claims` | List the claims register of a case | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/claims` | Filtered list of claims across cases (foreign-key reverse lookup) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/claims/{id}` | Get a claim | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/claims/{id}/dividends` | List dividends paid against a claim | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/claims/{id}/objections` | List objections filed against a claim | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/claims/{id}/encumbered_assets` | List assets encumbered by a secured claim | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/claims/{id}/review` | Move a claim from `FILED` to `UNDER_REVIEW` | Trustee |
| POST | `/trustee/claims/{id}/allow` | Allow an `UNDER_REVIEW` claim at its filed amount | Trustee |
| POST | `/trustee/claims/{id}/reopen` | Reopen an `ALLOWED` claim for reconsideration | Trustee |
| POST | `/trustee/claims/{id}/withdraw` | Creditor withdraws its own `FILED` or `UNDER_REVIEW` claim | Creditor |
| POST | `/trustee/claims/{id}/objections` | Trustee objects to an `UNDER_REVIEW` claim | Trustee |
| GET | `/trustee/cases/{id}/objections` | List objections of a case (filters: `status`, `claim_id`) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/objections/{id}` | Get an objection | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/objections/{id}/sustain` | Court sustains an objection; claim `DISALLOWED` | Court |
| POST | `/trustee/objections/{id}/overrule` | Court overrules an objection; claim `ALLOWED` as filed | Court |
| POST | `/trustee/objections/{id}/settle` | Trustee settles an objection (`ALLOW`, `DISALLOW`, or `PARTIAL`) | Trustee |
| POST | `/trustee/objections/{id}/withdraw` | Trustee withdraws an objection; claim returns to `UNDER_REVIEW` | Trustee |
| POST | `/trustee/cases/{id}/assets` | Schedule an asset discovered in investigation | Trustee, Clerk |
| GET | `/trustee/cases/{id}/assets` | List assets of a case (filter: `status`) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/assets/{id}` | Get an asset | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/assets/{id}/sales` | List sales of an asset | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/assets/{id}/investigate` | Move an asset from `SCHEDULED` to `UNDER_INVESTIGATION` | Trustee |
| POST | `/trustee/assets/{id}/mark_for_sale` | Move an asset from `UNDER_INVESTIGATION` to `MARKED_FOR_SALE` | Trustee |
| POST | `/trustee/assets/{id}/abandon` | Abandon an asset back to the debtor | Trustee |
| POST | `/trustee/assets/{id}/release_exemption` | Court releases an exempt asset | Court |
| POST | `/trustee/cases/{id}/sales` | Propose an auction sale of a `MARKED_FOR_SALE` asset | Trustee |
| GET | `/trustee/cases/{id}/sales` | List sales of a case (filters: `status`, `asset_id`) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/sales/{id}` | Get a sale | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/sales/{id}/approve` | Court approves a sale under the minimum-price gate | Court |
| POST | `/trustee/sales/{id}/consummate` | Post proceeds after the objection window; asset becomes `SOLD` | Trustee |
| POST | `/trustee/sales/{id}/cancel` | Cancel a sale; the asset returns to `MARKED_FOR_SALE` | Trustee, Court |
| POST | `/trustee/cases/{id}/avoidance_actions` | Register a preference or fraudulent-transfer action | Trustee |
| GET | `/trustee/cases/{id}/avoidance_actions` | List avoidance actions of a case | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/avoidance_actions/{id}` | Get an avoidance action | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/avoidance_actions/{id}/recovery_deposits` | List recovery deposits posted against an action | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/avoidance_actions/{id}/analyze` | Move an action from `IDENTIFIED` to `ANALYZED` | Trustee |
| POST | `/trustee/avoidance_actions/{id}/demand` | Move an action from `ANALYZED` to `DEMANDED` | Trustee |
| POST | `/trustee/avoidance_actions/{id}/settle` | Settle a demanded action; post the recovery deposit and claim-swap | Trustee |
| POST | `/trustee/avoidance_actions/{id}/enter_judgment` | Court enters judgment; post the full recovery deposit | Court |
| POST | `/trustee/avoidance_actions/{id}/rescind` | Court rescinds a judgment; void the deposit and debit the estate | Court |
| POST | `/trustee/avoidance_actions/{id}/abandon` | Abandon an `IDENTIFIED` or `ANALYZED` action | Trustee |
| GET | `/trustee/cases/{id}/recovery_deposits` | List recovery deposits of a case | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/recovery_deposits/{id}` | Get a recovery deposit | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/cases/{id}/plans` | Propose a distribution plan; snapshot the reserve and pool | Trustee |
| GET | `/trustee/cases/{id}/plans` | List distribution plans of a case (filter: `status`) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/plans/{id}` | Get a distribution plan | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/plans/{id}/confirm` | Court confirms a plan; the waterfall materializes dividends | Court |
| POST | `/trustee/plans/{id}/vacate` | Court vacates a `CONFIRMED` plan with no posted dividends | Court |
| GET | `/trustee/plans/{id}/allocations` | List class allocations of a plan | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/plans/{id}/dividends` | List dividends of a plan (filters: `status`, `claim_id`) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/dividends/{id}` | Get a dividend | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/dividends/{id}/post` | Post (pay) a `COMPUTED` dividend | Trustee |
| POST | `/trustee/dividends/{id}/void` | Void an unclaimed `COMPUTED` dividend | Trustee |
| POST | `/trustee/cases/{id}/fee_applications` | File a fee application (OCC-guarded; trustee commission computed server-side) | Trustee, Clerk |
| GET | `/trustee/cases/{id}/fee_applications` | List fee applications of a case | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/fee_applications/{id}` | Get a fee application | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/fee_applications/{id}/approve` | Court approves a fee at no more than the requested amount | Court |
| POST | `/trustee/fee_applications/{id}/deny` | Court denies a fee application | Court |
| POST | `/trustee/fee_applications/{id}/pay` | Trustee disburses an approved fee after its effective date | Trustee |
| GET | `/trustee/cases/{id}/final_report` | Get the case final report (an array of length 0–1) | Trustee, Clerk, Court, Creditor |
| GET | `/trustee/cases/{id}/allocations` | List plan class allocations across all plans of a case | Trustee, Clerk, Court, Creditor |
| POST | `/trustee/cases/{id}/final_report/file` | Trustee files the draft final report | Trustee |
| POST | `/trustee/cases/{id}/final_report/approve` | Court approves the final report; the case closes | Court |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the workflow narratives of §2 and §3; this catalogue is the authoritative identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_CLOSED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_ASSIGNED_TRUSTEE` | 403 Forbidden |
| `ERR_BAR_DATE_NOT_PASSED` | 409 Conflict |
| `ERR_INVALID_BAR_DATE` | 422 Unprocessable Entity |
| `ERR_NO_ASSETS_SCHEDULED` | 409 Conflict |
| `ERR_CLAIMS_UNREVIEWED` | 409 Conflict |
| `ERR_ASSETS_PENDING_SALE` | 409 Conflict |
| `ERR_OBJECTIONS_PENDING` | 409 Conflict |
| `ERR_NO_FUNDS_TO_DISTRIBUTE` | 409 Conflict |
| `ERR_PLAN_EXECUTING` | 409 Conflict |
| `ERR_PLAN_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CASE_NOT_IN_DISTRIBUTION` | 409 Conflict |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |
| `ERR_OBJECTION_ALREADY_PENDING` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_PARTIAL` | 422 Unprocessable Entity |
| `ERR_CASE_BEYOND_REOPEN` | 409 Conflict |
| `ERR_DIVIDEND_POSTED` | 409 Conflict |
| `ERR_ASSET_EXEMPT` | 409 Conflict |
| `ERR_SALE_ALREADY_PENDING` | 409 Conflict |
| `ERR_BELOW_MINIMUM_PRICE` | 422 Unprocessable Entity |
| `ERR_OBJECTION_WINDOW_OPEN` | 409 Conflict |
| `ERR_OBJECTION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_TRANSFER_NOT_AVOIDABLE` | 409 Conflict |
| `ERR_INVALID_DEMAND_AMOUNT` | 422 Unprocessable Entity |
| `ERR_PLAN_RELIES_ON_RECOVERY` | 409 Conflict |
| `ERR_APPROVAL_EXCEEDS_REQUEST` | 422 Unprocessable Entity |
| `ERR_FEE_NOT_YET_EFFECTIVE` | 409 Conflict |
| `ERR_INSUFFICIENT_ESTATE_FUNDS` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FINAL_REPORT_NOT_READY` | 409 Conflict |
