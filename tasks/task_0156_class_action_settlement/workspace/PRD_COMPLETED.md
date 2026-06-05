# Class Action Settlement Administration API — Product Requirements Document

## 1. Introduction

When a class action lawsuit settles, a court-supervised administrator must shepherd a fixed pool of money through a long and exacting lifecycle: notifying every class member, accepting and adjudicating their claims, curing defective filings, honoring opt-outs and objections, computing each claimant's award, paying it, reporting the tax consequences, and finally reconciling the fund so that not a single cent is unaccounted for. This API is the system of record for that process. It governs the **settlement fund** as a strict ledger, the **claims pipeline** as a branching review machine with a deficiency-cure revision loop, and the **distribution** as a quota-style allocation that can be posted, voided, or reversed.

The dominant design tension is fiscal: every dollar that enters the fund must leave it through exactly one of three doors — a payment to a valid claimant, a sweep to a charitable cy pres recipient, or a standing residual that has itself been recorded on the ledger. The system enforces this with an append-only ledger that must net to zero before a settlement can be closed, optimistic concurrency on the fund so that two controllers cannot both spend the same headroom, and a segregation-of-duties rule that bars the person who validated a claim from being the person who authorizes its payment. Throughout, all money is handled in integer cents — there are no fractional cents anywhere in the system, and every apportionment that would produce one is resolved by a deterministic largest-remainder rule.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Domain workflows and the rules that govern individual transitions live in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which they act. A request missing or carrying an unparseable value for either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a value of `X-User-Role` that does not name one of the six recognized roles counts as unparseable here and likewise yields `ERR_UNAUTHENTICATED`, not `ERR_FORBIDDEN_ROLE`. When the headers are present and the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `SettlementAdmin`, `FundController`, `ClaimsReviewer`, `ClaimsAdministrator`, `Claimant`, and `Court`. The `SettlementAdmin` is the hierarchical superset that configures the fund and drives its posture lifecycle (opening notice and claims windows, closing them, closing the settlement) and proposes cy pres recipients. The `FundController` owns the money: beginning distribution, computing/posting/voiding/reversing batches, reconciling the fund, and correcting tax forms. The `ClaimsReviewer` adjudicates claims — validating, rejecting, and raising deficiencies. The `ClaimsAdministrator` runs intake — registering members, sending notices, filing claims/opt-outs/objections on members' behalf, finalizing and revoking opt-outs, and processing cures. The `Court` is the judicial actor that approves or revokes cy pres designations and rules on objections.

Five of these roles carry an **opaque** identity. When `X-User-Role` is `SettlementAdmin`, `FundController`, `ClaimsReviewer`, `ClaimsAdministrator`, or `Court`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow needs it — most importantly, the system retains the identity of the `ClaimsReviewer` who validated each claim so that the segregation-of-duties rule can later compare it — but it does not treat that identifier as the `id` of any stored row.

The `Claimant` role is different: its identity is **entity-backed by `ClassMember`**. When `X-User-Role` is `Claimant`, the `X-User-ID` is the `id` of the acting `ClassMember`. An ownership check compares a resource's member foreign key to `X-User-ID`, but it is enforced only on the two operations that explicitly pin the acting claimant: self-serve claim filing (the path member must equal `X-User-ID`, §3.3) and objection withdrawal. In particular, a `Claimant` may only withdraw an objection they themselves filed: the acting claimant's `X-User-ID` must equal the objecting member referenced by the objection. Other claimant-permitted operations that name a `class_member_id` in the body — administrator-style claim filing via `POST /claims`, opt-out and objection creation, curing a claim — perform no such ownership check and act on whatever member the body or path names.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — an out-of-range value is silently clamped into that range (a `limit` below 1 becomes 1, above 100 becomes 100) rather than rejected, and a non-integer `limit` falls back to the default of 10. The `offset` parameter sets how many items to skip and defaults to 0; a negative or non-integer `offset` is likewise clamped or defaulted to 0. The reported `limit` and `offset` in `meta` reflect these effective (post-clamp) values. Unless a workflow states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Entity Mutation Semantics

Most resources in this system are full first-class entities and carry a standard set of system-managed fields. Every such resource has an `id` — a server-minted UUID with no type prefix — together with a `created_at` and an `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version`, an integer that begins at its initial value on creation and increments by one on every mutation that the relevant state machine declares. `created_at` is fixed at creation; `updated_at` is refreshed on every mutation. This convention applies to `Settlement`, `ClassMember`, `Claim`, `Deficiency`, `OptOutRequest`, `Objection`, `DistributionBatch`, `Payment`, `TaxForm`, and `CyPresDesignation`.

Two entities are deliberately leaner. A `NoticeRecord` and a `LedgerEntry` are immutable audit rows: each carries only an `id` and a `created_at`. Neither has an `updated_at` and neither has a `version`, because neither is ever mutated after it is written — they are append-only facts about what was sent or what was posted.

When a single request mutates several entities, each entity that is mutated independently has its own `updated_at` refreshed and, if it is a versioned entity, its own `version` incremented. The state-machine descriptions in §3 are explicit about which entities a given transition touches; a controller posting a batch, for example, advances both the batch's version and the settlement's version because both are genuinely mutated.

### 2.5. Nested Resource Retrieval and Existence Ordering

Several endpoints address a child through a parent in the URL — for example, listing the notices of a member or the cy pres designations of a settlement. For any such path, the system validates each identifier left-to-right and rejects the request at the first identifier that does not resolve. A request against a path-referenced settlement (or any other primary path resource) that does not exist is rejected with `ERR_SETTLEMENT_NOT_FOUND` (HTTP 404). This existence check on path resources is evaluated before any body-level or business rule. Separately, when a create request names a foreign key in its body — `settlement_id`, `class_member_id`, `claim_id`, `distribution_batch_id`, `payment_id`, or `supersedes_claim_id` — and that key points to no existing row, the request is rejected with `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404).

### 2.6. Monetary Precision and Integer-Cent Arithmetic

All money in this system is expressed and stored as integer cents; no field ever holds a fractional cent. Where an allocation divides a pool by weights or basis points and the exact quotient is not a whole number, the system takes the integer floor for each recipient and then distributes the leftover cents one apiece by a largest-remainder rule (detailed in §3 for both the pro-rata distribution and the cy pres sweep). The result is exact: the sum of the floored shares plus the distributed leftover cents always equals the pool being divided, so reconciliation never drifts by rounding. Basis-point shares are interpreted against a denominator of 10000.

### 2.7. The Settlement Ledger and the Zero-Sum Invariant

Each settlement owns an append-only ledger of `LedgerEntry` rows. Every entry records a `settlement_id`, an `entry_type`, a signed `amount_cents` (debits negative, credits positive), and a `reference_id` identifying the entity that produced it — a `Payment` id, a `CyPresDesignation` id, or the settlement's own id for the fund-open, fee, and admin entries. The `entry_type` is one of `FUND_OPEN`, `FEE_DEBIT`, `ADMIN_DEBIT`, `PAYMENT_DEBIT`, `PAYMENT_REVERSAL_CREDIT`, or `CY_PRES_DEBIT`.

The governing invariant is that the signed `amount_cents` of all ledger entries for a settlement must sum to exactly zero before that settlement can be closed. Concretely the ledger accumulates: the gross fund as a positive `FUND_OPEN` entry; the attorney fee and the administration cost as negative `FEE_DEBIT` and `ADMIN_DEBIT` entries; one negative `PAYMENT_DEBIT` per committed payment; one positive `PAYMENT_REVERSAL_CREDIT` per reversed payment; and one negative `CY_PRES_DEBIT` per funded cy pres recipient. A read-only balance endpoint computes this sum on demand — summing the signed `amount_cents` of every `LedgerEntry` for the settlement, with no entry excluded — and returns it as a `balance_cents` field alongside the fund's `net_distributable_cents`, `allocated_cents`, and `residual_cents` (the response is a bare object carrying exactly these four integer fields, with none of the standard entity system fields). The expected balance for a closable settlement is exactly zero; the close transition recomputes the same sum and refuses to proceed unless it is zero.

### 2.8. Derived Fund Figures

Three figures on a settlement are computed rather than supplied. The `net_distributable_cents` is the gross fund minus the attorney fee minus the administration cost; because all three inputs are immutable after creation, it is computed once at creation and never drifts thereafter. The `allocated_cents` is the running sum of cents committed to payment rows across all posted distribution batches of the settlement; it is recomputed on every batch post and every batch reverse. The `residual_cents` is computed at reconciliation as the net distributable amount minus the allocated amount minus whatever was swept to cy pres, and it must equal zero when the settlement reaches its reconciled posture.

### 2.9. Optimistic Concurrency on the Fund

Two fund-mutating operations are guarded by optimistic concurrency against the `Settlement` parent, and both name the concurrency field `expected_settlement_version`.

A request to post a distribution batch must carry `expected_settlement_version` carrying the client's last observed `version` of the owning settlement. If that value does not equal the settlement's current `version`, the post is rejected with `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412). This captures the case in which another batch has already posted, debited the fund, and advanced the settlement's `version` since the current writer last read it: the budget headroom the writer reasoned about is now stale, and the guard forces a re-read before any further commitment.

Likewise, a request to reconcile a settlement must carry `expected_settlement_version` matching the settlement's current `version`; a mismatch is rejected with the same `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412). A reconcile that began from a fund snapshot taken before a late batch post would compute a residual that no longer matches the ledger, so the guard compels a re-read so that the swept residual and the cy pres allocations are computed from the current `allocated_cents`. No other endpoint takes a version field; operations not named here do not perform an OCC check.

### 2.10. Segregation of Duties

The administration enforces a separation between the person who adjudicates a claim and the person who pays it. The `FundController` who posts a distribution batch must not be the same operator — compared by `X-User-ID` — as the `ClaimsReviewer` who validated any claim paid in that batch. A post that would violate this is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This is why the system records the validating reviewer's identity at validation time, as noted in §2.1.

### 2.11. Request-Shape and Enumeration Validation

Two request-shape checks apply broadly. Any create or transition endpoint that declares required body fields rejects a request missing one of them with `ERR_MISSING_REQUIRED_FIELD` (HTTP 422). Any endpoint that accepts an enum-typed body field — `distribution_method`, `claimant_tier`, `channel`, `delivery_status`, `reason_code`, `form_type`, or the objection `ruling` — rejects a value outside that field's declared set with `ERR_INVALID_ENUM` (HTTP 422). These checks concern request shape and are evaluated early — right after the role check and after any path-resource existence check (so a missing path resource is reported first), but before body foreign-key existence and before every membership, posture, timing, and business-constraint check below; the enum check is evaluated just before the missing-field check on the same operation. Their numeric rank is nominally listed last in §2.12 only because they never form a dual-failure conflict pair with the business rules, but in actual evaluation order they precede those body-level and business checks rather than trailing them.

### 2.12. Validation Priority and Conflict Resolution

When more than one validation could fire on a single request, the system evaluates them in a fixed priority order and returns the error of the first that fails. The order from highest to lowest precedence is: authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then path-resource existence (`ERR_SETTLEMENT_NOT_FOUND`), then body foreign-key existence (`ERR_REFERENCED_ENTITY_NOT_FOUND`), then member-settlement membership (`ERR_MEMBER_SETTLEMENT_MISMATCH`), then the state-transition legality check (`ERR_INVALID_STATE`), then the owning-settlement posture check (`ERR_SETTLEMENT_POSTURE_INVALID`), then the timing windows (claim window, then objection/opt-out window, then cure window), then the business constraints in the numeric order given in §3 (member-has-claim, member-excluded, recognized-exceeds-claimed, invalid-supersede, segregation-of-duties, cy-pres-shares-unbalanced, fund-exceeded, stale-version, duplicate-email), and finally — though in actual evaluation order the request-shape checks fire early, right after role and after path-existence but before body foreign-key existence and the business checks above, as detailed in §2.11 — the request-shape checks (invalid enum, then missing field) and the deficiency-blocks-validation check. Where a section below lists several checks for one operation, that listed order is the order in which they are evaluated.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Settlement Fund

A `SettlementAdmin` creates a settlement by supplying its `case_caption` (a human-readable name such as "In re Acme Data Breach"), the `gross_fund_cents` (the total fund before any deduction, which must be at least 1), the `attorney_fee_cents` and `admin_cost_cents` (each at least 0), the `distribution_method` (either `PRO_RATA` or `TIERED`), the two deadline instants `claim_filing_deadline` and `objection_deadline`, and three optional figures. The optional `tier_a_amount_cents` and `tier_b_amount_cents` (each at least 0, defaulting to 0) are the flat per-tier awards used only under the tiered method and ignored otherwise. The optional `cy_pres_floor_cents` (at least 0, defaulting to 0) is the per-claimant minimum economic-distribution threshold below which a leftover residual is swept to charity rather than left standing. On creation the settlement is born in `DRAFT`, its `net_distributable_cents` is computed immediately, and both `allocated_cents` and `residual_cents` begin at 0.

The fund advances through a posture lifecycle that gates every child operation: `DRAFT → NOTICE_OPEN → CLAIMS_OPEN → CLAIMS_CLOSED → DISTRIBUTING → RECONCILED → CLOSED`. A `SettlementAdmin` opens notice on a settlement that is in `DRAFT`; this is permitted only if the cy pres side of the fund is already coherent — that is, either at least one cy pres recipient already sits in `APPROVED`, or the `cy_pres_floor_cents` is 0 so no sweep can ever be needed. Opening notice sets the posture to `NOTICE_OPEN` and, crucially, opens the ledger: it appends a `FUND_OPEN` entry of positive `gross_fund_cents`, a `FEE_DEBIT` of negative `attorney_fee_cents`, and an `ADMIN_DEBIT` of negative `admin_cost_cents`, each referencing the settlement's own id, and increments the settlement's version. If the posture is not `DRAFT`, the transition is rejected as an invalid state with `ERR_INVALID_STATE`.

From `NOTICE_OPEN`, the same administrator opens the claims window, moving the posture to `CLAIMS_OPEN`; this requires that at least one class member already exists under the settlement. Later the administrator closes the claims window, but only once the logical clock is at or after the `claim_filing_deadline` — an attempt before that instant is an invalid-state rejection. Closing the claims window sweeps the deficiency backlog: for every still-open deficiency whose own cure window has elapsed (its `cure_deadline` at or before now), the deficiency is expired and its claim is driven to `REJECTED` through the rejection cascade described in §3.4. Each of these posture transitions increments the settlement's version.

Once claims are closed, the money side takes over. A `FundController` begins distribution — moving the posture from `CLAIMS_CLOSED` to `DISTRIBUTING` — provided at least one validated claim exists; otherwise there is nothing to pay and the transition is an invalid-state rejection. After all batches are resolved, the controller reconciles the fund (§3.7), and finally the administrator closes it (§3.8). Every operation that mutates a child checks that the owning settlement is in a posture that permits it: filing a claim requires `CLAIMS_OPEN`, an opt-out request requires `NOTICE_OPEN` or `CLAIMS_OPEN`, an objection likewise requires the settlement be in `NOTICE_OPEN` or `CLAIMS_OPEN` (the same window-open posture as an opt-out), and a batch may only be created while `DISTRIBUTING`. A child operation attempted against a settlement in the wrong posture is rejected with `ERR_SETTLEMENT_POSTURE_INVALID` (HTTP 409). Settlements may be fetched individually or listed (filterable by `status`) by any role.

### 3.2. Class Members and Notice

A `ClaimsAdministrator` registers a class member under a settlement by supplying the member's `full_name`, `email`, an optional `claimant_tier` (either `TIER_A` or `TIER_B`, defaulting to `TIER_B`), and an optional `tin_on_file` flag (defaulting to false). The `claimant_tier` is the pre-adjudicated damages tier consulted by the tiered distribution method; `tin_on_file` records whether a valid taxpayer identification number is held, which later gates both tax-form issuance and backup withholding. A member is born in `NOTIFIED` with a `notice_count` of 0. Email must be unique within a settlement: registering a second member with an email already present under that settlement is rejected with `ERR_DUPLICATE_MEMBER_EMAIL` (HTTP 409). Members may be fetched individually or listed, filterable by `settlement_id` and `status`.

The administrator records each notice sent to a member by supplying the `channel` (one of `EMAIL`, `MAIL`, or `PUBLICATION`) and the `delivery_status` reported by the delivery vendor (one of `DELIVERED`, `BOUNCED`, or `RETURNED`). Each recorded notice creates a `NoticeRecord` referencing the member through `class_member_id` and increments that member's `notice_count` by one; because this mutates the member, the member's `updated_at` is refreshed and its `version` is incremented as well. The notices of a given member can be listed back.

A member's participation posture is `NOTIFIED`, `PARTICIPATING`, or `EXCLUDED`. The system moves a `NOTIFIED` member to `PARTICIPATING` automatically the first time a claim is created for them, provided no effective opt-out exists for that member. The system moves a `NOTIFIED` member to `EXCLUDED` automatically when an opt-out for that member becomes effective. And if a participating member's only live claim is rejected and no other claim of theirs remains in `SUBMITTED`, `DEFICIENT`, `CURED`, `VALIDATED`, or `PAID`, the member falls back from `PARTICIPATING` to `NOTIFIED`; should that member later refile a superseding claim, the act of creating it returns them to `PARTICIPATING`.

### 3.3. Filing and Adjudicating Claims

A claim asserts a member's loss against a settlement. It can be filed by a `ClaimsAdministrator` or `Claimant` by supplying the `settlement_id`, the `class_member_id`, the asserted `claimed_loss_cents` (at least 0), and an optional `supersedes_claim_id`. A claimant may instead use the self-serve filing convenience, which pins the member from the path and takes only the `settlement_id`, the `claimed_loss_cents`, and an optional `supersedes_claim_id`; the path member must resolve (else `ERR_SETTLEMENT_NOT_FOUND`) and the acting claimant's `X-User-ID` must equal that path member, or the request is refused with `ERR_FORBIDDEN_ROLE`. Either way a claim is born in `SUBMITTED` with `recognized_loss_cents`, `open_deficiency_count`, and `paid_amount_cents` all at 0, and the act of creating it promotes a `NOTIFIED` claimant to `PARTICIPATING` as described in §3.2.

Several gates guard claim creation. The named member must belong to the same settlement named in the body, or the request is rejected with `ERR_MEMBER_SETTLEMENT_MISMATCH` (HTTP 422). A claim must be filed strictly before the settlement's `claim_filing_deadline` — a filing with the clock at or after that instant is untimely and rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422). A member who has been excluded cannot file at all; such an attempt is rejected with `ERR_MEMBER_EXCLUDED` (HTTP 409). When `supersedes_claim_id` is present the filing is a refile, and the superseded claim must be a `REJECTED` claim belonging to the same member and must not itself already have been superseded; a refile that breaks either condition is rejected with `ERR_INVALID_SUPERSEDE` (HTTP 422). Claims may be fetched individually and listed, filterable by `settlement_id`, `class_member_id`, `supersedes_claim_id`, and `status`.

A `ClaimsReviewer` adjudicates each claim. The claim machine is `SUBMITTED → {VALIDATED, DEFICIENT}`, with a deficiency-cure revision loop `DEFICIENT → CURED → {VALIDATED, DEFICIENT}` and a rejection door reachable from `SUBMITTED`, `DEFICIENT`, or `CURED`. Validating a claim — driving it from `SUBMITTED` to `VALIDATED`, or from `CURED` to `VALIDATED` — requires that the claim currently sit in `SUBMITTED` or `CURED`, that it carry no open deficiencies, and that the owning settlement be in `CLAIMS_OPEN` or `CLAIMS_CLOSED`. The reviewer supplies the `recognized_loss_cents`, which becomes the claim's recognized loss and its pro-rata weight; this supplied amount must not exceed the claim's `claimed_loss_cents`, or the request is rejected with `ERR_RECOGNIZED_EXCEEDS_CLAIMED` (HTTP 422). If the claim still has any open deficiency the validation is blocked with `ERR_VALIDATION_BLOCKED_BY_DEFICIENCY` (HTTP 409). A successful validation sets `recognized_loss_cents` to the supplied value, moves the claim to `VALIDATED`, and increments the claim's version.

### 3.4. Deficiencies, Cures, and Rejection

When a reviewer finds a claim defective, they raise a deficiency against it, supplying a `reason_code` (one of `MISSING_PROOF`, `SIGNATURE_MISSING`, `IDENTITY_UNVERIFIED`, or `DUPLICATE_SUSPECTED`) and a `cure_deadline` instant. Raising a deficiency creates a `Deficiency` row in `OPEN` referencing its `claim_id`, increments the claim's `open_deficiency_count`, drives the claim to `DEFICIENT`, and increments the claim's version. A deficiency may be raised on a claim that is in `SUBMITTED` or one that is in `CURED`; these two branches share their structure — both create an open deficiency, bump the open-deficiency count, set the claim to `DEFICIENT`, and advance the claim's version — but differ in one respect: raising the very first deficiency on a fresh `SUBMITTED` claim is part of that claim's initial branching, whereas raising one on a `CURED` claim is the re-entry into the revision loop and fires no member transition. Deficiencies of a claim can be listed (filterable by `status`) and fetched individually.

The claimant — or a `ClaimsAdministrator` acting for them — cures a deficient claim, driving it from `DEFICIENT` to `CURED`. A cure is permitted only when every open deficiency on the claim still has a `cure_deadline` strictly after the clock; if the clock has reached or passed any open deficiency's cure deadline, the cure is untimely and rejected with `ERR_CURE_WINDOW_CLOSED` (HTTP 422). A successful cure cascades down to every open deficiency child, setting each to `CURED`, resets the claim's `open_deficiency_count` to 0, moves the claim to `CURED`, and increments the claim's version. From `CURED` the claim can be validated again or sent back into `DEFICIENT` by a fresh deficiency, closing the revision loop.

A `ClaimsReviewer` may reject a claim that is in `SUBMITTED`, `DEFICIENT`, or `CURED`, driving it to the terminal `REJECTED`. Rejection expires every open deficiency child (each `OPEN` deficiency becomes `EXPIRED`), resets the claim's `open_deficiency_count` to 0, increments the claim's version, and bubbles up to the member: if the claimant has no remaining non-rejected claim, the member falls from `PARTICIPATING` back to `NOTIFIED`. The same rejection-with-cascade also fires automatically as part of closing the claims window, where each open deficiency past its cure deadline is expired and its claim driven to `REJECTED`. A deficiency therefore reaches its terminal `EXPIRED` either through this claims-close sweep or through an explicit claim rejection, and reaches its terminal `CURED` only through its owning claim's cure transition.

### 3.5. Opt-Outs and Objections

A member may ask to be excluded from the settlement. A `ClaimsAdministrator` or `Claimant` requests an opt-out by supplying the `settlement_id` and `class_member_id`; the request is born in `REQUESTED`. The named member must belong to the named settlement (otherwise `ERR_MEMBER_SETTLEMENT_MISMATCH`), and the request must be filed strictly before the settlement's `objection_deadline` — at or after that instant it is untimely and rejected with `ERR_OBJECTION_WINDOW_CLOSED` (HTTP 422). Opt-out requests can be fetched individually and listed, filterable by `settlement_id` and `status`.

A `ClaimsAdministrator` finalizes an opt-out, moving it from `REQUESTED` to `EFFECTIVE`. Finalization is permitted only while the owning settlement is in `NOTICE_OPEN` or `CLAIMS_OPEN`, and only if the member has no non-rejected claim — participation and exclusion are mutually exclusive, so finalizing for a member who holds any claim that is not `REJECTED` is refused with `ERR_MEMBER_HAS_CLAIM` (HTTP 409). A successful finalization sets the request to `EFFECTIVE` and, as a cross-entity effect, sets the member's status to `EXCLUDED`. The same administrator may later revoke an effective opt-out, again only while the settlement is in `NOTICE_OPEN` or `CLAIMS_OPEN`; revoking moves the request to the terminal `REVOKED` and restores the member to `NOTIFIED`.

An objection is a member's challenge to the settlement on stated grounds. A `ClaimsAdministrator` or `Claimant` files one by supplying the `settlement_id`, the `class_member_id`, and free-text `grounds`; it is born in `FILED`. Like an opt-out, an objection must name a member belonging to the settlement and must be filed strictly before the `objection_deadline`, on pain of the same membership and timing rejections. The `Court` rules on a filed objection by supplying a `ruling` that drives it to either the terminal `SUSTAINED` or the terminal `OVERRULED`; both rulings act on a claim in `FILED` and are symmetric, each simply setting the objection to the corresponding terminal status. Separately, the objecting `Claimant` may withdraw their own filed objection, moving it to the terminal `WITHDRAWN`; only the member who filed the objection (matched by `X-User-ID`) may withdraw it, and a withdrawal attempt by any other claimant is refused with `ERR_FORBIDDEN_ROLE` (the objection-must-be-`FILED` state check is evaluated first, also as `ERR_INVALID_STATE`). Objections can be fetched and listed, filterable by `settlement_id` and `status`.

### 3.6. Computing and Posting a Distribution

Once a settlement is `DISTRIBUTING`, a `FundController` creates a distribution batch by supplying the `settlement_id` and a `sequence_no` (at least 1). The sequence number is a human label only; when several batches contend for the same fund they are processed oldest-first by `created_at`, not by sequence number. A batch is born in `DRAFT` with `planned_total_cents`, `posted_total_cents`, and `residual_after_cents` all at 0, and runs through `DRAFT → COMPUTED → {POSTED, VOID}`, with a posted batch further reversible to `REVERSED`. Batches can be fetched and listed, filterable by `settlement_id` and `status`.

**Computing the batch.** The controller computes a `DRAFT` batch, moving it to `COMPUTED`. Computation runs the allocation over the **eligible claims**: every claim of this settlement that is `VALIDATED`, has a `paid_amount_cents` of 0, and whose owning member is `PARTICIPATING`. The eligible claims are processed in `created_at` ascending order. Computation creates one planned `Payment` per eligible claim — each referencing its `distribution_batch_id` and `claim_id` and born in `PLANNED` — populating each payment's `gross_amount_cents`, `withholding_cents`, and `amount_cents`, then sets the batch's `planned_total_cents` to the sum of the payments' `amount_cents` and advances the batch's version.

The gross award depends on the settlement's method. Under `PRO_RATA`, the pool being divided is the **remaining headroom** — the settlement's `net_distributable_cents` minus its `allocated_cents` — and it is apportioned by largest remainder weighted by each claim's `recognized_loss_cents`. Let the total recognized loss be the sum of `recognized_loss_cents` over the eligible claims. For each claim, the exact weighted share is the remaining headroom multiplied by that claim's recognized loss divided by the total recognized loss; the claim's provisional gross is the integer floor of that exact share. The floored grosses will fall short of the headroom by a number of leftover cents between 0 and one fewer than the count of eligible claims. These leftover cents are handed out one each, to the claims ordered by the fractional part of their exact share descending, ties broken by `created_at` ascending — never by id; each such claim's gross is raised by one cent until the leftover is exhausted. Because the leftover is distributed in full, the pro-rata grosses sum to exactly the headroom, leaving no residual within the batch.

Under `TIERED`, each eligible claim instead receives a flat award read from the settlement: a claim whose member's `claimant_tier` is `TIER_A` receives `tier_a_amount_cents`, and a claim whose member's tier is `TIER_B` receives `tier_b_amount_cents`. (For total iteration, tiered claims are walked in `created_at` ascending order, ties broken by claim id ascending, but this ordering never changes any award.) The tiered awards are summed into `planned_total_cents` un-capped — the batch is not truncated at compute time. The resulting tiered total may come out below the remaining headroom, in which case the shortfall stands as a residual eligible for cy pres, or above it, in which case the batch is not silently trimmed but is rejected later at post time as described below.

**Withholding.** After each claim's gross is fixed, backup withholding is applied per claim. For a claim whose member has no taxpayer identification on file and whose gross is at least the tax reporting threshold of 60000 cents (six hundred dollars), the `withholding_cents` is the integer floor of the gross multiplied by the backup withholding rate of 2400 basis points — that is, twenty-four percent of the gross, floored to whole cents. For every other claim the withholding is 0. Each payment's `amount_cents` — the net cents that will actually debit the fund — is its gross minus its withholding.

**Posting the batch.** The controller posts a `COMPUTED` batch, supplying `expected_settlement_version` for the optimistic-concurrency guard of §2.9. Posting is gated on three further conditions evaluated in this order: the segregation-of-duties rule of §2.10 (the posting controller must not be the reviewer who validated any claim in the batch, else `ERR_SEGREGATION_OF_DUTIES`); the stale-version guard (`ERR_STALE_SETTLEMENT_VERSION` on mismatch); and the fund-capacity check — the batch's `planned_total_cents` must not exceed the remaining headroom (`net_distributable_cents` minus `allocated_cents`), or the post is rejected with `ERR_FUND_EXCEEDED` (HTTP 422). A successful post commits every payment in the batch (each moves from `PLANNED` to `COMMITTED`); cascades each paid claim from `VALIDATED` to `PAID`, setting that claim's `paid_amount_cents` to its payment's `amount_cents`; appends one negative `PAYMENT_DEBIT` ledger entry per payment of `amount_cents`; increases the settlement's `allocated_cents` by the posted total and sets the batch's `posted_total_cents` to its `planned_total_cents`; sets the batch's `residual_after_cents` to the net distributable amount minus the now-updated allocated amount; issues tax forms for the qualifying payments (§3.9); sets the batch to `POSTED`; and increments the settlement's version.

**Voiding the batch.** Alternatively, the controller voids a `COMPUTED` batch. Voiding is the divergent sibling of posting: it cancels every planned payment in the batch (each `PLANNED` payment becomes `CANCELLED`), sets the batch to the terminal `VOID`, and increments the batch's version — with no ledger impact, no claim transition, and no tax forms. The payments of a batch can be listed (filterable by `status`), and individual payments can be fetched or listed (filterable by `claim_id`, `distribution_batch_id`, and `status`).

### 3.7. Reversing a Posted Batch and Reconciling the Fund

A `FundController` may reverse a `POSTED` batch, but only while the settlement is still `DISTRIBUTING` (otherwise the reversal is refused with `ERR_SETTLEMENT_POSTURE_INVALID`) and only if no tax form referencing a payment in that batch has already been voided (otherwise it is refused with `ERR_INVALID_STATE`); the batch's own state legality — it must be `POSTED` — is itself checked as `ERR_INVALID_STATE` before either of these. Reversal is the compensating mirror of posting: every committed payment in the batch moves to `REVERSED`; each paid claim reverts from `PAID` back to `VALIDATED` with its `paid_amount_cents` reset to 0; one positive `PAYMENT_REVERSAL_CREDIT` ledger entry of `amount_cents` is appended per payment; the settlement's `allocated_cents` is decreased by the batch's posted total; every tax form referencing a payment in the batch is voided; and both the batch's version and the settlement's version are incremented. A committed payment thus reaches its terminal `REVERSED` only through its batch's reversal, just as a planned payment reaches its terminal `CANCELLED` only through its batch's void.

When all batches are resolved — none left in `COMPUTED`, every one `POSTED`, `VOID`, or `REVERSED` — the controller reconciles the settlement, supplying `expected_settlement_version`. Reconciliation first computes the residual as `net_distributable_cents` minus `allocated_cents`. If that residual is strictly greater than 0 and strictly less than the settlement's `cy_pres_floor_cents`, it is too small to redistribute and is swept to charity: the cy pres sweep (§3.8) runs, each approved cy pres recipient is funded and moved to `FUNDED`, the corresponding `CY_PRES_DEBIT` ledger entries are appended, and the residual is driven to 0. If instead the residual is strictly greater than 0 but at least the floor, it is left standing as an acknowledged residual eligible for a further batch, and reconciliation still proceeds and records that standing residual into `residual_cents`. If the residual is 0 or negative (the fund is fully or over-allocated), no sweep runs and the settlement's `residual_cents` is recorded as 0. Either way the settlement moves to `RECONCILED` and its version increments. Reconciliation is refused if the cy pres shares are unbalanced (§3.8) or if the stale-version guard fires; these are evaluated in that order — the cy-pres-shares-unbalanced check (which fires only when the sub-floor sweep would actually run) precedes the stale-version guard — both of which themselves follow the `DISTRIBUTING`-state check and the no-batch-still-`COMPUTED` check (each surfaced as `ERR_INVALID_STATE`).

### 3.8. Cy Pres Recipients and the Residual Sweep

Before notice even opens, a `SettlementAdmin` may propose charitable cy pres recipients, each supplying a `recipient_name` and a `share_bps` (basis points of the swept residual, between 1 and 10000 inclusive). Proposing is not gated on the settlement's posture — a designation may be proposed in any posture, not only `DRAFT` — and the only path check is that the named settlement exists. A designation is born in `PROPOSED` with `funded_cents` at 0. The `Court` approves a proposed designation, moving it to `APPROVED`, which is permitted while the settlement is in any of `DRAFT`, `NOTICE_OPEN`, `CLAIMS_OPEN`, `CLAIMS_CLOSED`, or `DISTRIBUTING`. The court may instead revoke a still-proposed designation, moving it to the terminal `REVOKED`. Designations can be fetched individually and listed under their settlement (filterable by `status`).

The cy pres sweep runs during reconciliation, and only when the residual is strictly between 0 and the `cy_pres_floor_cents`. Its precondition is that the basis-point shares of all approved designations sum to exactly 10000; if they do not, reconciliation is rejected with `ERR_CY_PRES_SHARES_UNBALANCED` (HTTP 422). The sweep divides the residual among the approved recipients, processed in `created_at` ascending order, by the same largest-remainder discipline used for pro-rata: each recipient's floored share is the integer floor of the residual multiplied by that recipient's `share_bps` divided by 10000, and the leftover cents — between 0 and one fewer than the recipient count — are handed out one each to the recipients ordered by the fractional part of their exact share descending, ties broken by `created_at` ascending (never by id). Each recipient's `funded_cents` is its floored share plus the one leftover cent if it received one. The funded amounts sum to exactly the residual, so the sweep zeroes it precisely.

### 3.9. Tax Reporting

When a batch posts, the system issues a tax form for each committed payment whose claimant has no taxpayer identification on file and whose `gross_amount_cents` is at least the 60000-cent reporting threshold — the same population subjected to backup withholding. A `TaxForm` references its `payment_id` and the payee through `class_member_id`, carries a `form_type` (either `1099_MISC`, the default, or `1099_NEC`), and is born in `ISSUED`. On issuance its `reportable_cents` is set to the payment's `gross_amount_cents` and its `withheld_cents` to the payment's `withholding_cents`.

A `FundController` may correct a form that is in `ISSUED`, provided the referenced payment is still `COMMITTED`; a form not in `ISSUED`, or one whose referenced payment is not `COMMITTED`, is refused with `ERR_INVALID_STATE`. Correction refreshes `reportable_cents` from the payment's current `gross_amount_cents` and `withheld_cents` from its `withholding_cents`, moves the form to `CORRECTED`, and increments the form's version. A tax form reaches its terminal `VOIDED` automatically when its owning batch is reversed — from either `ISSUED` or `CORRECTED`. Tax forms can be fetched individually and listed, filterable by `payment_id`, `class_member_id`, and `status`.

### 3.10. Closing the Settlement

After reconciliation, a `SettlementAdmin` closes the settlement, moving it from `RECONCILED` to the terminal `CLOSED`. Closure is permitted only when the ledger nets to zero — the signed `amount_cents` of every `LedgerEntry` for the settlement summing to exactly 0, per §2.7. If the ledger does not balance, the close is refused as an invalid state. A successful close increments the settlement's version. At that point every distributable cent has left the fund through a payment, a cy pres sweep, or a recorded standing residual offset, and the case is administratively complete.

### 3.11. Test-Driving the Clock

Because so many rules turn on deadlines — the claim window, the objection and opt-out window, and each deficiency's cure window — an administrative capability lets a `SettlementAdmin` set the server's notion of current UTC for these deadline-gated checks. The caller supplies a `to_iso8601` instant, and the server adopts it as the logical "now" against which all window comparisons are made, returning the new current UTC as a `current_utc` field on the response object.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including every state-machine transition and every administrative action — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/settlements` | Create a settlement fund in DRAFT | SettlementAdmin |
| GET | `/settlements/{id}` | Fetch a settlement | SettlementAdmin, FundController, ClaimsReviewer, ClaimsAdministrator, Court |
| GET | `/settlements` | List settlements (paginated) | SettlementAdmin, FundController, ClaimsReviewer, ClaimsAdministrator, Court |
| POST | `/settlements/{id}/open-notice` | DRAFT → NOTICE_OPEN; opens the fund ledger | SettlementAdmin |
| POST | `/settlements/{id}/open-claims` | NOTICE_OPEN → CLAIMS_OPEN | SettlementAdmin |
| POST | `/settlements/{id}/close-claims` | CLAIMS_OPEN → CLAIMS_CLOSED; expires overdue open deficiencies and rejects their claims | SettlementAdmin |
| POST | `/settlements/{id}/begin-distribution` | CLAIMS_CLOSED → DISTRIBUTING | FundController |
| POST | `/settlements/{id}/reconcile` | DISTRIBUTING → RECONCILED; sweeps sub-floor residual to cy pres | FundController |
| POST | `/settlements/{id}/close` | RECONCILED → CLOSED; requires zero ledger balance | SettlementAdmin |
| GET | `/settlements/{id}/ledger-balance` | Computed read: ledger balance over LedgerEntry rows | SettlementAdmin, FundController |
| GET | `/settlements/{id}/ledger-entries` | List LedgerEntry children of a settlement (filterable by `entry_type`) | SettlementAdmin, FundController |
| POST | `/settlements/{id}/class-members` | Register a class member under a settlement (NOTIFIED) | ClaimsAdministrator |
| GET | `/class-members/{id}` | Fetch a class member | ClaimsAdministrator, ClaimsReviewer, FundController, Claimant |
| GET | `/class-members` | List class members, filterable by settlement | ClaimsAdministrator, ClaimsReviewer, FundController |
| POST | `/class-members/{id}/notices` | Record a notice sent to a member; increments notice_count | ClaimsAdministrator |
| GET | `/class-members/{id}/notices` | List NoticeRecord children of a member | ClaimsAdministrator, ClaimsReviewer |
| POST | `/class-members/{id}/file-claim` | Self-serve claim filing by the claimant | Claimant |
| POST | `/claims` | File a claim (administrator-entered) | ClaimsAdministrator, Claimant |
| GET | `/claims/{id}` | Fetch a claim | ClaimsReviewer, ClaimsAdministrator, FundController, Claimant |
| GET | `/claims` | List claims; filterable by settlement, member, supersede, status | ClaimsReviewer, ClaimsAdministrator, FundController |
| POST | `/claims/{id}/validate` | SUBMITTED\|CURED → VALIDATED; sets recognized_loss_cents | ClaimsReviewer |
| POST | `/claims/{id}/reject` | SUBMITTED\|DEFICIENT\|CURED → REJECTED | ClaimsReviewer |
| POST | `/claims/{id}/cure` | DEFICIENT → CURED; resolves all open deficiencies | Claimant, ClaimsAdministrator |
| POST | `/claims/{id}/deficiencies` | Raise a deficiency; SUBMITTED\|CURED → DEFICIENT | ClaimsReviewer |
| GET | `/claims/{id}/deficiencies` | List Deficiency children of a claim | ClaimsReviewer, ClaimsAdministrator, Claimant |
| GET | `/deficiencies/{id}` | Fetch a deficiency | ClaimsReviewer, ClaimsAdministrator, Claimant |
| POST | `/opt-outs` | Request exclusion from a settlement (REQUESTED) | ClaimsAdministrator, Claimant |
| GET | `/opt-outs/{id}` | Fetch an opt-out request | ClaimsAdministrator, Claimant, FundController |
| GET | `/opt-outs` | List opt-out requests | ClaimsAdministrator, FundController |
| POST | `/opt-outs/{id}/finalize` | REQUESTED → EFFECTIVE; excludes the member | ClaimsAdministrator |
| POST | `/opt-outs/{id}/revoke` | EFFECTIVE → REVOKED; restores the member to NOTIFIED | ClaimsAdministrator |
| POST | `/objections` | File an objection (FILED) | ClaimsAdministrator, Claimant |
| GET | `/objections/{id}` | Fetch an objection | ClaimsAdministrator, Claimant, Court, FundController |
| GET | `/objections` | List objections | ClaimsAdministrator, Court, FundController |
| POST | `/objections/{id}/rule` | FILED → SUSTAINED\|OVERRULED by the Court | Court |
| POST | `/objections/{id}/withdraw` | FILED → WITHDRAWN by the objecting member | Claimant |
| POST | `/distribution-batches` | Create a distribution batch in DRAFT | FundController |
| GET | `/distribution-batches/{id}` | Fetch a distribution batch | FundController, SettlementAdmin |
| GET | `/distribution-batches` | List distribution batches | FundController, SettlementAdmin |
| POST | `/distribution-batches/{id}/compute` | DRAFT → COMPUTED; runs allocation, creates PLANNED payments | FundController |
| POST | `/distribution-batches/{id}/post` | COMPUTED → POSTED; commits payments, debits fund, pays claims, issues tax forms | FundController |
| POST | `/distribution-batches/{id}/void` | COMPUTED → VOID; cancels planned payments | FundController |
| POST | `/distribution-batches/{id}/reverse` | POSTED → REVERSED; compensates ledger, reverts claims, voids tax forms | FundController |
| GET | `/distribution-batches/{id}/payments` | List Payment children of a batch | FundController, SettlementAdmin |
| GET | `/payments/{id}` | Fetch a payment | FundController, SettlementAdmin, ClaimsReviewer |
| GET | `/payments` | List payments; filterable by claim | FundController, SettlementAdmin, ClaimsReviewer |
| GET | `/tax-forms/{id}` | Fetch a tax form | FundController, SettlementAdmin |
| GET | `/tax-forms` | List tax forms; filterable by payment and member | FundController, SettlementAdmin |
| POST | `/tax-forms/{id}/correct` | ISSUED → CORRECTED; refreshes reportable/withheld amounts | FundController |
| POST | `/settlements/{id}/cy-pres-designations` | Propose a cy pres recipient (PROPOSED) | SettlementAdmin |
| GET | `/cy-pres-designations/{id}` | Fetch a cy pres designation | SettlementAdmin, FundController, Court |
| GET | `/settlements/{id}/cy-pres-designations` | List CyPresDesignation children of a settlement | SettlementAdmin, FundController, Court |
| POST | `/cy-pres-designations/{id}/approve` | PROPOSED → APPROVED by the Court | Court |
| POST | `/cy-pres-designations/{id}/revoke` | PROPOSED → REVOKED by the Court | Court |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC | SettlementAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_REFERENCED_ENTITY_NOT_FOUND` | 404 |
| `ERR_MEMBER_SETTLEMENT_MISMATCH` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SETTLEMENT_POSTURE_INVALID` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_OBJECTION_WINDOW_CLOSED` | 422 |
| `ERR_CURE_WINDOW_CLOSED` | 422 |
| `ERR_MEMBER_HAS_CLAIM` | 409 |
| `ERR_MEMBER_EXCLUDED` | 409 |
| `ERR_RECOGNIZED_EXCEEDS_CLAIMED` | 422 |
| `ERR_INVALID_SUPERSEDE` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CY_PRES_SHARES_UNBALANCED` | 422 |
| `ERR_FUND_EXCEEDED` | 422 |
| `ERR_STALE_SETTLEMENT_VERSION` | 412 |
| `ERR_DUPLICATE_MEMBER_EMAIL` | 409 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_MISSING_REQUIRED_FIELD` | 422 |
| `ERR_VALIDATION_BLOCKED_BY_DEFICIENCY` | 409 |
