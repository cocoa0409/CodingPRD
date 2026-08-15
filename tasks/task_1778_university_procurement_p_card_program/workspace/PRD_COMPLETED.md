# University Procurement & P-Card Program API — Product Requirements Document

## 1. Introduction

A university purchasing office sits at the intersection of academic urgency and public-money accountability. Departments want lab supplies, software, travel, and equipment bought quickly; sponsors and auditors want every dollar traced to an allowable cost category, every large purchase competitively sourced, and every payment supported by a receipt. This document specifies an API that runs the full procurement lifecycle for that office: requisitions that flow through a dollar-tiered approval pipeline, competitive solicitations with weighted award scoring, contract drafting and negotiation with exclusivity enforcement, grant-funded allowability and budget-ledger checks, purchase orders settled through a three-way match, a purchasing-card program with limits, statement cycles, and dispute handling, and finally the disposal of surplus property with a regulated sharing of sale proceeds.

The design goals are determinism, auditability, and strict segregation of duties. Every approval decision is recorded on an immutable audit trail; every financial rule — approval thresholds, grant indirect-cost recovery, invoice tolerance, card utilization, award scoring, surplus proceeds — is computed by the server from pinned inputs rather than trusted from the client; and every deadline, window, and aging rule reads a controllable logical clock rather than the wall clock, so that the entire program can be exercised reproducibly. A requester may never approve their own requisition, and no one may resolve an invoice exception on a purchase they originally requested. The API is mounted at the service root and speaks JSON throughout.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing or blank, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly eleven roles: `Requester`, `DepartmentApprover`, `Buyer`, `ProcurementDirector`, `ContractOfficer`, `GrantOfficer`, `APClerk`, `ReceivingClerk`, `Cardholder`, `SurplusManager`, and `ProcurementAdmin`. Beyond authentication, each operation is restricted to a designated role set; an attempt by a role outside that set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). One deliberate exception to that generic code exists in surplus sales: a high-value sale attempted by a `SurplusManager` is reported as `ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR` rather than `ERR_FORBIDDEN_ROLE`, because the distinction matters for audit review.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `PCard`; ownership checks on any resource that references a `PCard` compare the resource's `pcard_id` field to `X-User-ID`. For every other role — `Requester`, `DepartmentApprover`, `Buyer`, `ProcurementDirector`, `ContractOfficer`, `GrantOfficer`, `APClerk`, `ReceivingClerk`, `SurplusManager`, and `ProcurementAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `requester_id` on a requisition at creation, as `actor_id` on an approval record, as `received_by` on a receipt, or as `variance_accepted_by` on an invoice), and ownership checks then compare `X-User-ID` against those recorded fields, but the identifier is never compared to any entity's `id`. Two segregation-of-duties rules follow from this model and are absolute: an approver deciding a requisition step must not be the requisition's requester, and an accounts payable clerk resolving an invoice exception must not be the requester of the requisition that funded the purchase.

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
- Requests that never reach a defined endpoint still fail in this envelope: an undefined path yields `ERR_INVALID_REQUEST` with HTTP 404, and a defined path called with an unsupported method yields `ERR_INVALID_REQUEST` with HTTP 400.

### 2.3. Pagination

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned; it defaults to 10 when omitted and must lie between 1 and 100 inclusive. `offset` sets the number of items skipped and defaults to 0; it may never be negative. A `limit` outside the allowed range or a negative `offset` is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400), as is a non-integer `limit` or `offset`. Unless a more specific ordering is stated, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object. Several list endpoints additionally accept domain filters — for example `status`, `department_id`, `vendor_id`, `grant_id`, `contract_id`, `requisition_id`, `fulfillment_status`, `match_status`, `pcard_id`, or `claiming_department_id` — which restrict the listed collection to matching records, and the supplier-diversity report accepts `basis`, `window_start`, and `window_end`.

### 2.4. The Logical Clock

All deadline, window, period, and aging rules in the program — grant budget periods, contract effective periods, solicitation deadlines, redistribution windows, anti-splitting rolling windows, elevation windows, and statement-cycle aging — read a single server-side **logical clock**, never the wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ProcurementAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`, which echoes the supplied `to_iso8601` string verbatim; setting the clock mutates no entity. Wherever this document says "the logical clock" or "at the current logical time", it refers to this clock.

### 2.5. Common Resource Properties and Versioning

Every primary resource in the system — departments, vendors, grants, contracts, requisitions, solicitations, quotes, purchase orders, receipts, invoices, P-cards, limit elevations, P-card transactions, and surplus assets — carries a standard set of system-managed fields:

- `id` — a server-minted UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, initialized equal to `created_at` and refreshed on every mutation of the resource.
- `version` — a system-managed integer starting at 1 at creation that increments on every mutation, including server-initiated mutations such as cascade transitions. Purely derived fields — the grant ledger positions, a purchase order's match posture, a card's utilization — are recomputed on read, and their recomputation is not a mutation of the owning resource: it neither refreshes `updated_at` nor increments `version` (see §2.10).

`created_at`, `updated_at`, and the envelope's `api_request_timestamp` are stamped from the wall clock; only the domain-event stamps named in §3 (`submitted_at`, `issued_at`, `received_at`, `paid_at`, `posted_at`, `declared_at`, `executed_at`, `awarded_at`, `reconciled_at`, `decided_at`) read the logical clock.

The single exception is the approval audit record, which is immutable once written: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it.

### 2.6. Money, Precision, and Rounding

All monetary amounts in the system are integer cents; fields such as `total_cents`, `charge_cents`, `value_cents`, `amount_cents`, and `sale_price_cents` are integers, and the arithmetic that produces them uses integer operations with no rounding. Where a rule genuinely produces a fraction, the document states so at the point of use, and the rounding method is always **round half up**: the grant indirect-cost calculation rounds once to whole cents, the invoice three-way match rounds each line's tolerance to whole cents before any summation, the surplus proceeds waterfall rounds the departmental share to whole cents, and the surplus sale floor rounds its percentage component to whole cents. Two derived figures are decimal rather than integer: quote award scores are rounded half up to exactly 2 decimal places, applied once at the end of the scoring formula, and supplier-diversity ratios are rounded half up to exactly 4 decimal places. Rates and goal fractions supplied by clients (such as `f_and_a_rate` or `diversity_goal_pct`) preserve input precision.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each names its own expected-version field:

- Editing a requisition requires `expected_requisition_version`, carrying the client's last observed `version` of that requisition. If the requisition's current `version` has advanced — for example because an approver acted on it — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the requisition before resubmitting.
- Creating a contract amendment requires `expected_contract_version`, carrying the client's last observed `version` of the contract being amended. Because a prior amendment created against the same contract legitimately supersedes the client's view, a mismatch is refused with `ERR_STALE_VERSION` (HTTP 412) rather than producing two competing amendment drafts.
- Changing a P-card's limits requires `expected_pcard_version`, carrying the client's last observed `version` of the card. A mismatch — for instance because a close-cycle or another limits change bumped the version — is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here take no version field at all; in particular, state-transition operations elsewhere in the program rely on lifecycle preconditions, not client-supplied versions.

### 2.8. Validation Priority Order

Every request passes through a fixed validation ladder, and the rungs are evaluated in the following order — a failure on an earlier rung prevents any later rung from being evaluated, so the error a client observes is always the earliest applicable one:

1. **User context** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the acting role is in the endpoint's allowed role set (`ERR_FORBIDDEN_ROLE`).
3. **Existence** — path identifiers exist, validated left to right, and identifiers referenced in the request body (such as `department_id`, `vendor_id`, `grant_id`, `contract_id`, or `claiming_department_id`) exist (the 404 family described in §2.9).
4. **Ownership** — where an operation is owner-scoped, `X-User-ID` matches the owning field (`ERR_NOT_RESOURCE_OWNER`).
5. **Stale versions** — on the three OCC-guarded writes, the expected-version field matches the parent's current `version` (`ERR_STALE_VERSION`).
6. **Lifecycle preconditions** — the target resource is in a state from which the requested transition exists, including approval step-role matching on approval decisions (the lifecycle 409 family: `ERR_REQUISITION_NOT_SUBMITTABLE`, `ERR_REQUISITION_NOT_EDITABLE`, `ERR_REQUISITION_NOT_IN_APPROVAL`, `ERR_REQUISITION_NOT_CANCELLABLE`, `ERR_REQUISITION_NOT_APPROVED`, `ERR_APPROVAL_STEP_MISMATCH`, `ERR_CONTRACT_STATE_INVALID`, `ERR_SOLICITATION_NOT_OPEN`, `ERR_SOLICITATION_NOT_CLOSED`, `ERR_SOLICITATION_NOT_CANCELLABLE`, `ERR_PO_NOT_RECEIVABLE`, `ERR_PO_NOT_CANCELLABLE`, `ERR_PO_NOT_INVOICABLE`, `ERR_PO_INVOICING_CLOSED`, `ERR_RECEIPT_NOT_VOIDABLE`, `ERR_INVOICE_NOT_RESOLVABLE`, `ERR_INVOICE_NOT_PAYABLE`, `ERR_CARD_STATE_INVALID`, `ERR_CARD_NOT_ACTIVE`, `ERR_CARD_CLOSED`, `ERR_CARD_HAS_OPEN_TRANSACTIONS`, `ERR_TXN_NOT_RECONCILABLE`, `ERR_TXN_NOT_DISPUTABLE`, `ERR_TXN_NOT_DISPUTED`, `ERR_SURPLUS_NOT_CLAIMABLE`, `ERR_SURPLUS_NOT_LISTABLE`, `ERR_SURPLUS_NOT_SELLABLE`, `ERR_SURPLUS_NOT_DONATABLE`, `ERR_SURPLUS_NOT_SCRAPPABLE`, `ERR_GRANT_STATE_INVALID`, `ERR_VENDOR_STATE_INVALID`, `ERR_ELEVATION_STATE_INVALID`).
7. **Compliance and segregation of duties** — the approver is not the requester (`ERR_SELF_APPROVAL_FORBIDDEN`), the exception resolver is not the requester (`ERR_SELF_RESOLUTION_FORBIDDEN`), the surplus claimant is not the owning department (`ERR_SELF_CLAIM_FORBIDDEN`), grant cost-category allowability (`ERR_GRANT_CATEGORY_NOT_ALLOWABLE`), grant budget-period coverage (`ERR_GRANT_BUDGET_PERIOD_EXPIRED`), merchant-category restriction (`ERR_MCC_NOT_ALLOWED`), and sole-source justification completeness (`ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED`).
8. **Clock-driven temporal rules** — solicitation quote windows and close deadlines (`ERR_SOLICITATION_EXPIRED`, `ERR_SOLICITATION_DEADLINE_NOT_PASSED`), contract effective period at purchase-order issuance (`ERR_CONTRACT_EXPIRED`), the surplus redistribution window on claiming and listing (`ERR_REDISTRIBUTION_WINDOW_EXPIRED`, `ERR_REDISTRIBUTION_WINDOW_ACTIVE`), and the anti-splitting rolling aggregate (`ERR_BID_SPLITTING_DETECTED`).
9. **Structural constraints** — contract period exclusivity (`ERR_CONTRACT_OVERLAP`), elevation-window overlap and gap rules (`ERR_ELEVATION_OVERLAP`, `ERR_ELEVATION_GAP_VIOLATION`), one quote per vendor per solicitation (`ERR_DUPLICATE_QUOTE`), the sourcing gate at the purchasing step (`ERR_SOURCING_REQUIRED`), eligible-pool and top-score rules at award (`ERR_NO_ELIGIBLE_QUOTES`, `ERR_INSUFFICIENT_QUOTES`, `ERR_AWARD_NOT_TOP_SCORE`), over-receipt (`ERR_OVER_RECEIPT`), invoice line existence (`ERR_INVOICE_LINE_UNKNOWN`), card-limit consistency (`ERR_LIMIT_INCONSISTENT`), grant-close encumbrance (`ERR_GRANT_HAS_OPEN_ENCUMBRANCES`, which on the close operation is evaluated before the lifecycle rung), and solicitation creation guards (`ERR_SOLICITATION_NOT_ALLOWED`, `ERR_SOLICITATION_ALREADY_EXISTS`).
10. **Referenced-entity status** — the vendor is `ACTIVE` where required (`ERR_VENDOR_SUSPENDED`), the grant is `ACTIVE` where required (`ERR_GRANT_NOT_ACTIVE`), and the contract is `EXECUTED` where required (`ERR_CONTRACT_NOT_EXECUTED`).
11. **Money ceilings** — the department delegated limit at the department approval step (`ERR_APPROVER_LIMIT_EXCEEDED`), grant remaining budget (`ERR_GRANT_BUDGET_EXCEEDED`), P-card single-transaction and monthly ceilings (`ERR_SINGLE_TXN_LIMIT_EXCEEDED`, `ERR_MONTHLY_LIMIT_EXCEEDED`), and surplus sale floors and role gating (`ERR_SALE_PRICE_BELOW_FLOOR`, `ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR`).
12. **Request shape** — required fields present, enum members valid, quantities and amounts positive, `effective_start` strictly before `effective_end`, `window_start` strictly before `window_end`, and pagination within bounds (`ERR_INVALID_REQUEST`, `ERR_INVALID_PAGINATION_PARAMETERS`). Shape validation is listed last because malformed bodies never reach business checks; implementations may short-circuit earlier, but must never return a business error for a malformed body. Unknown or system-managed fields supplied by the client (for example a client-sent `total_cents` or `status`) are ignored rather than rejected, an explicit JSON null on an optional field is treated as the field being absent except where a workflow states otherwise, and numeric fields carry no range checks beyond the rules named at the point of use.

### 2.9. Existence and Reference Resolution

The entity graph is flat: resources are joined by foreign-key references carried in request bodies and response fields rather than by deep URL nesting for ownership. Wherever a path does contain more than one identifier — for example a child collection under a parent resource — the identifiers are validated strictly left to right, and the request is rejected with the 404 error corresponding to the first identifier that does not resolve: `ERR_DEPARTMENT_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_PO_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_PCARD_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_ELEVATION_NOT_FOUND`, or `ERR_SURPLUS_ASSET_NOT_FOUND`, each with HTTP 404. Identifiers referenced inside a request body are checked for existence at the same rung of the ladder. Read-side reverse reachability is provided so that every stored reference can be walked: quotes are listable by vendor, solicitations by requisition, receipts and invoices by purchase order, transactions by card, and a cross-card transaction listing can be filtered by `grant_id`.

### 2.10. Cross-Entity Consistency, Cascades, and Derived Reconciliation

Many operations in this program mutate more than one resource, and the server performs those mutations atomically and immediately — there is no eventual consistency window. Suspending a vendor disqualifies live quotes and can unwind awarded solicitations and in-flight requisitions; terminating a contract flags purchase orders, flips payable invoices into exception, and returns approved requisitions; voiding a receipt recomputes fulfillment and re-matches open invoices; closing a statement cycle can suspend a card. Server-initiated transitions of this kind are first-class mutations: every affected resource refreshes its `updated_at` and increments its `version`. Derived fields — a grant's ledger positions, a purchase order's match posture, a card's utilization — are recomputed on read at the moment any input to them changes; such recomputation is not itself a mutation of the owning resource and neither refreshes its `updated_at` nor increments its `version`. Two status dimensions of a purchase order evolve in parallel and are kept strictly separate: receipts drive fulfillment only, while invoices and contract cascades drive match posture only — with one deliberate exception, the receipt-void re-match described in §3.5, which touches both.

## 3. Business Logic & Workflows

### 3.1. Program Foundations: Departments, Vendors, and Grants

Everything in the program anchors on three registries. A **department** is created by a `ProcurementAdmin` with a display `name`, a `cost_center` code, two planning goals — `diversity_goal_pct` and `sustainability_goal_pct`, each expressed as a fraction of spend (for example 0.25) — and a `default_approval_limit_cents`, the delegated authority ceiling that will be enforced when requisitions of this department reach their department approval step. The diversity goal is later evaluated by the spend reporting described in §3.10; the sustainability goal is recorded on the department for program planning.

A **vendor** is registered by a `Buyer` with a `legal_name` and three optional attributes: `diversity_certification`, one of `NONE`, `WBE`, `MBE`, `DBE`, `VBE`, or `SBE` and defaulting to `NONE`; `sustainability_tier`, one of `NONE`, `BRONZE`, `SILVER`, or `GOLD` and likewise defaulting to `NONE`; and `payment_terms_days`, the net payment terms, defaulting to 30 days. A new vendor starts `ACTIVE`. A `ProcurementAdmin` may suspend an `ACTIVE` vendor — an optional `reason` may accompany the suspension and is accepted but not recorded — or reinstate a `SUSPENDED` one; calling either transition against a vendor in the wrong state is rejected with `ERR_VENDOR_STATE_INVALID`. Suspension is deliberately heavy-handed: every quote from that vendor still `SUBMITTED` on an `OPEN` or `CLOSED` solicitation is immediately `DISQUALIFIED`; if the vendor held an awarded quote, that quote too is disqualified and its `AWARDED` solicitation collapses to `CANCELLED`; and any requisition referenced by such a cancelled solicitation that is currently `SUBMITTED` is returned to its requester in `RETURNED` status with `returned_reason` recorded as `VENDOR_SUSPENDED`, its approval progress discarded. Reinstatement is merciful but not retroactive — it does not resurrect disqualified quotes or cancelled solicitations. Operations elsewhere that require an active vendor — submitting a requisition that names one, submitting a quote on one, executing a contract with one — are rejected with `ERR_VENDOR_SUSPENDED` while the vendor is suspended.

A **grant** is administered by a `GrantOfficer`, who creates it with a `grant_code`, a `sponsor` name, the `total_award_cents`, the facilities-and-administrative rate `f_and_a_rate` (for example 0.52), an `allowed_categories` array drawn from the cost categories `SUPPLIES`, `EQUIPMENT`, `TRAVEL`, `SERVICES`, and `SOFTWARE`, and the inclusive budget period bounded by `budget_start` and `budget_end`, both compared against the logical clock. The per-unit capitalization threshold `equipment_cap_cents` defaults to 500,000 cents (5,000 dollars) when not supplied; any grant-funded line whose unit price is strictly above that threshold is treated as capital equipment and excluded from the indirect-cost base. A new grant is `ACTIVE` with both ledger positions initialized to zero. The `GrantOfficer` may suspend an `ACTIVE` grant, reinstate a `SUSPENDED` one, or close an `ACTIVE` one; a transition attempted from the wrong state is rejected with `ERR_GRANT_STATE_INVALID`, and closing is additionally refused with `ERR_GRANT_HAS_OPEN_ENCUMBRANCES` while the grant's `encumbered_cents` is anything other than zero — on close this encumbrance guard is evaluated before the state guard, so closing a non-`ACTIVE` grant that still carries encumbrances surfaces `ERR_GRANT_HAS_OPEN_ENCUMBRANCES`. `CLOSED` is terminal. Suspending a grant blocks new grant-funded submissions and new grant-allocated reconciliations: both require the grant to be `ACTIVE`, surfacing `ERR_GRANT_NOT_ACTIVE` otherwise.

The grant's four ledger figures are computed, never stored by hand. `spent_cents` accumulates settled charges: the `charge_cents` of the grant's purchase orders whose invoice has been paid, plus reconciled grant-allocated P-card debits, with reversed ones subtracting back out. A grant-allocated debit that is disputed after having been reconciled remains inside `spent_cents` while the dispute is open; only a `REVERSED` one subtracts back out. `encumbered_cents` accumulates outstanding commitments: the `charge_cents` of the grant's requisitions sitting in `APPROVED`, plus the `charge_cents` of the grant's purchase orders that are not `CANCELLED` and whose invoice has not been paid. Two remaining-budget variants are derived from these: `provisional_remaining_cents` is the total award minus both spent and encumbered amounts and is the variant consulted by allowability checks and forward planning, while `settled_remaining_cents` subtracts only settled spend and is the variant used for reporting actually-incurred cost. The ledger is conserved: spent, encumbered, and provisional remaining always sum back to `total_award_cents`. Both variants are exposed through a dedicated computed budget-ledger view of the grant.

### 3.2. Contract Lifecycle: Drafting, Negotiation, Execution, Amendment, and Termination

A `ContractOfficer` drafts a **contract** by naming its counterparty `vendor_id`, the `commodity_code` it covers, a `value_cents` ceiling, the effective period `effective_start` through `effective_end`, and optionally the negotiated `terms_text`. The period is half-open: the start is inclusive and the end is exclusive. The start must be strictly earlier than the end, or creation fails with `ERR_INVALID_REQUEST`. A new contract is `DRAFT`, its `negotiation_round` is zero, `supersedes_contract_id` is null, and both `executed_at` and `terminated_reason` are null.

Review and negotiation form a loop. Submitting for review moves a contract from `DRAFT` — or from `IN_NEGOTIATION`, when a revised draft comes back — into `UNDER_REVIEW`. From `UNDER_REVIEW` the officer may open a negotiation round, moving the contract to `IN_NEGOTIATION` and incrementing `negotiation_round` by one each time (an optional `note` may accompany the round and is accepted but not recorded), or may approve the review, moving it to `REVIEW_APPROVED`. Every one of these transitions attempted from a state where it does not exist is rejected with `ERR_CONTRACT_STATE_INVALID`.

Execution belongs to the `ProcurementDirector` and is guarded four ways. The contract must be `REVIEW_APPROVED` (otherwise `ERR_CONTRACT_STATE_INVALID`); the counterparty vendor must be `ACTIVE` (otherwise `ERR_VENDOR_SUSPENDED`); the effective period must still be internally consistent, start strictly before end (otherwise `ERR_INVALID_REQUEST`); and exclusivity must hold — no other `EXECUTED` contract may exist for the same pairing of `vendor_id` and `commodity_code` whose half-open period overlaps this one, excepting the contract this one is explicitly superseding (otherwise `ERR_CONTRACT_OVERLAP`). On execution the contract becomes `EXECUTED`, `executed_at` is stamped with the logical clock, and if `supersedes_contract_id` names a predecessor, that predecessor — which must itself be `EXECUTED`, failing which the execution is rejected with `ERR_CONTRACT_STATE_INVALID` — is moved to `SUPERSEDED`. Both `TERMINATED` and `SUPERSEDED` are terminal.

Amendments are new drafts, not edits in place. A `ContractOfficer` creates an amendment against an `EXECUTED` contract, supplying the new `effective_start` and `effective_end` and optionally a revised `value_cents` or `terms_text`, each defaulting to the amended contract's current value when omitted; the vendor and commodity code are inherited from the amended contract. The amendment is created in `DRAFT` with its `supersedes_contract_id` pointing at the contract it will replace, and the act of creating it increments the amended contract's `version` by one — which is precisely why amendment creation is OCC-guarded: the request must carry `expected_contract_version` matching the amended contract's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. When the amendment itself later executes, the supersede machinery above replaces the original.

Termination, also by the `ProcurementDirector`, requires the contract to be `EXECUTED` and a non-empty `reason`, which is recorded into `terminated_reason`. Its blast radius is significant and immediate: every purchase order riding this contract whose fulfillment is anything other than `CANCELLED` — `ISSUED`, `PARTIALLY_RECEIVED`, or `FULLY_RECEIVED` — has its `contract_terminated_flag` set to true, which forces its match posture to `EXCEPTION` regardless of invoices; every invoice on such a purchase order that is currently `PAYABLE` flips to `EXCEPTION` with `exception_reason` `CONTRACT_TERMINATED`; and every requisition riding this contract that is `APPROVED` but has not yet issued its purchase order is moved to `RETURNED` with `returned_reason` `CONTRACT_TERMINATED`.

### 3.3. The Requisition Pipeline: Drafting, Submission, and the Approval Chain

A requisition begins when a `Requester` creates it with its owning `department_id`, their own opaque `requester_id`, and a non-empty set of `lines`. Each line carries a `commodity_code`, a free-text `description`, a `quantity`, a `unit_price_cents`, and a `cost_category` drawn from `SUPPLIES`, `EQUIPMENT`, `TRAVEL`, `SERVICES`, or `SOFTWARE`; the server assigns each line a `line_no` from its position in the array, starting at zero. Optional references shape the rest of the pipeline: a suggested `vendor_id` (left null while a competitive solicitation is pending award), a `grant_id` that makes the requisition grant-funded, and a `contract_id` that makes it ride an existing contract. The requester may also set `sole_source_requested`, defaulting to false, with an accompanying `sole_source_justification`. At creation the requisition is `DRAFT`, the server mints its human-readable `requisition_number` in the sequential `RQ-000001` format, and `total_cents` is computed as the exact integer sum over all lines of quantity times unit price, with no rounding. The boolean `has_grant_funding` reflects simply whether `grant_id` is set. Both `submitted_at` and `returned_reason` remain null until events fill them, and before the first submission `required_chain` reads as an empty array, `current_step_index` as zero, and `charge_cents` as null. Once recorded, `returned_reason` is retained through later edits and resubmissions until another return overwrites it.

While the requisition is `DRAFT` or `RETURNED`, the requester may edit it; editing from any other status is rejected with `ERR_REQUISITION_NOT_EDITABLE`. The edit is owner-scoped — an `X-User-ID` other than the recorded `requester_id` is refused with `ERR_NOT_RESOURCE_OWNER` — and OCC-guarded: the payload must carry `expected_requisition_version` matching the requisition's current `version`, with mismatches rejected as `ERR_STALE_VERSION`. The requester may replace `lines`, `vendor_id`, `grant_id`, `contract_id`, `sole_source_requested`, or `sole_source_justification`; an explicit null on `vendor_id`, `grant_id`, `contract_id`, or `sole_source_justification` clears that field, while a null `lines` is treated as absent. When the lines change, `total_cents` is recomputed; `has_grant_funding` is re-derived from the resulting `grant_id` on every edit; and every successful edit increments the requisition's `version` by one.

Submission is the pipeline's great gate, and its checks run in a defined sequence against the ladder of §2.8. The requisition must be `DRAFT` or `RETURNED` (otherwise `ERR_REQUISITION_NOT_SUBMITTABLE`), submitted by its owner (otherwise `ERR_NOT_RESOURCE_OWNER`), and structurally sound: at least one line, every quantity strictly positive, and every unit price non-negative (otherwise `ERR_INVALID_REQUEST`). If the requisition is grant-funded, the grant must be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`), every line's `cost_category` must appear in the grant's `allowed_categories` (otherwise `ERR_GRANT_CATEGORY_NOT_ALLOWABLE`), and the logical clock must fall inside the inclusive budget period from `budget_start` through `budget_end` (otherwise `ERR_GRANT_BUDGET_PERIOD_EXPIRED`). Sole-source requests face a two-sided rule: when `sole_source_requested` is set and the total reaches 5,000 dollars (500,000 cents), a non-empty `sole_source_justification` is mandatory (otherwise `ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED`); when the total is below that mark, requesting sole source at all is malformed and rejected with `ERR_INVALID_REQUEST`. A requisition naming a contract requires that contract to be `EXECUTED` (otherwise `ERR_CONTRACT_NOT_EXECUTED`), and one naming a vendor requires the vendor to be `ACTIVE` (otherwise `ERR_VENDOR_SUSPENDED`).

One further guard fights purchase splitting. Whenever a submitted requisition does not ride a contract, names a vendor, and totals less than 25,000 dollars, the system sums `total_cents` over the same department's other requisitions to the same vendor whose `submitted_at` falls inside the rolling window that ends at the logical clock and begins thirty days earlier — both ends of the window inclusive — and whose status is `SUBMITTED`, `APPROVED`, or `PO_ISSUED`. Requisitions still drafting, returned, or cancelled never enter the sum, and requisitions riding a contract neither enter it nor trigger the check at all. If the rolling sum plus the new requisition's own total reaches 2,500,000 cents — equality included — the submission is rejected with `ERR_BID_SPLITTING_DETECTED`.

A successful submission stamps `submitted_at` with the logical clock and pins the approval route. The chain always opens with a `DEPARTMENT` step. A `GRANT_COMPLIANCE` step follows whenever the requisition is grant-funded. A `SOLE_SOURCE` step is added when the requester asked to waive competition and the total reaches 500,000 cents. A `PURCHASING` step is added whenever the total reaches 500,000 cents. A `DIRECTOR` step is added when the total reaches 2,500,000 cents, and a `CONTRACT_REVIEW` step when it reaches 10,000,000 cents. All thresholds are inclusive: a total of exactly 500,000 cents includes the `PURCHASING` step. The ordered result is frozen onto `required_chain`, `current_step_index` starts at zero, and `charge_cents` — the amount that will be charged to the funding source — is computed. For an ungrant-funded requisition `charge_cents` is simply `total_cents`. For a grant-funded one it is computed in a pinned order: first the equipment exclusion, the sum of quantity times unit price over lines whose `cost_category` is `EQUIPMENT` and whose unit price is strictly greater than the grant's `equipment_cap_cents` — a unit price exactly equal to the cap is not excluded; then the direct cost, which is the requisition's `total_cents`; then the indirect cost, the grant's `f_and_a_rate` multiplied by the direct cost minus the equipment exclusion, rounded half up to whole cents, which is the only rounding step; and finally `charge_cents` is the direct cost plus the indirect cost. When the requisition rides a contract, its `sourcing_method` is set to `EXISTING_CONTRACT` at submission; otherwise it remains `UNDETERMINED` until a sole-source step is approved or a solicitation is awarded, which set it to `SOLE_SOURCE` or `COMPETITIVE_BID` respectively.

While the requisition is `SUBMITTED`, the chain steps are decided in order, each by exactly one acting role: `DEPARTMENT` by a `DepartmentApprover`, `GRANT_COMPLIANCE` by a `GrantOfficer`, `SOLE_SOURCE` and `DIRECTOR` by the `ProcurementDirector`, `PURCHASING` by a `Buyer`, and `CONTRACT_REVIEW` by a `ContractOfficer`. Approving or returning from a status other than `SUBMITTED` is rejected with `ERR_REQUISITION_NOT_IN_APPROVAL`; acting with a role that does not match the step named by `required_chain` at `current_step_index` is rejected with `ERR_APPROVAL_STEP_MISMATCH`; and any approver whose `X-User-ID` equals the requisition's `requester_id` is refused with `ERR_SELF_APPROVAL_FORBIDDEN` on both decisions. Two step-level gates add money and sourcing checks: at a `DEPARTMENT` step, the department's `default_approval_limit_cents` must cover the requisition's `total_cents`, or the decision is rejected with `ERR_APPROVER_LIMIT_EXCEEDED`; and at a `PURCHASING` step, when the total is at least 2,500,000 cents and the requisition neither rides a contract nor carries an approved sole source, an awarded solicitation for this requisition must already exist, or the decision is rejected with `ERR_SOURCING_REQUIRED`.

Each approval — an optional `comment` may accompany it — appends an immutable audit record and advances `current_step_index` by one. Approving a `SOLE_SOURCE` step additionally sets `sole_source_approved` to true (a flag that, once set, is never reset) and moves `sourcing_method` to `SOLE_SOURCE`. Approving the final chain step adds one more gate and one more effect: for a grant-funded requisition the grant's `provisional_remaining_cents` must cover the requisition's `charge_cents` — the full charge including indirect cost, not merely the direct total — or the decision is rejected with `ERR_GRANT_BUDGET_EXCEEDED` (HTTP 402); on success the requisition becomes `APPROVED` and its `charge_cents` is added to the grant's `encumbered_cents`. Returning, which requires a non-empty `reason`, appends the corresponding audit record, moves the requisition to `RETURNED`, and records `returned_reason`; the step index is not rewound at that moment — it resets only when the requisition is resubmitted. Every decision is captured as an audit record bearing the `requisition_id`, the decided `step_index`, the `step_role` code, the deciding `actor_id`, the `decision` (`APPROVED` or `RETURNED`), the `reason` when returned (null otherwise), and the `decided_at` logical timestamp; the full chronological trail is listable per requisition.

The requester may cancel their own requisition from `DRAFT`, `RETURNED`, or `APPROVED`; from any other status — including `SUBMITTED`, where an approver holds the pen — cancellation is rejected with `ERR_REQUISITION_NOT_CANCELLABLE`, and a non-owner attempt is `ERR_NOT_RESOURCE_OWNER`. Cancelling from `APPROVED` releases the grant encumbrance by subtracting `charge_cents` from `encumbered_cents`. A resubmission from `RETURNED` re-runs the entire submission gate, recomputes and re-pins the chain snapshot and the charge, and retains the earlier audit records as history.

### 3.4. Competitive Sourcing: Solicitations, Quotes, and Award

When a requisition is too large for informal purchasing and rides no contract, a `Buyer` opens a **bid solicitation** for it. Creation requires the requisition to be `SUBMITTED` with a `total_cents` of at least 2,500,000 cents and no `contract_id`; any other configuration is rejected with `ERR_SOLICITATION_NOT_ALLOWED`, and because at most one non-cancelled solicitation may exist per requisition, a second live one is rejected with `ERR_SOLICITATION_ALREADY_EXISTS`. The buyer supplies a `response_deadline` — which is not validated against the logical clock at creation — and optionally a `min_quotes`, which defaults to 3 and must be at least 1 (otherwise `ERR_INVALID_REQUEST`). The solicitation opens in `OPEN` status, with `awarded_quote_id` and `awarded_at` null.

Vendors quote through the buyer while the solicitation is `OPEN` — submitting against one that is not is rejected with `ERR_SOLICITATION_NOT_OPEN`, which is also the error for closing a solicitation that is not `OPEN`. Each quote names a `vendor_id` and a `price_cents` that must be strictly positive (otherwise `ERR_INVALID_REQUEST`); the bidding vendor must be `ACTIVE` (otherwise `ERR_VENDOR_SUSPENDED`), and a vendor may hold only one `SUBMITTED` quote per solicitation, a second attempt being rejected with `ERR_DUPLICATE_QUOTE`. Quotes are accepted only while the logical clock is strictly earlier than the `response_deadline`; at or after the deadline, submission fails with `ERR_SOLICITATION_EXPIRED`. Each accepted quote is stamped `SUBMITTED`, bound to its parent through `solicitation_id`, given a `submitted_at` from the logical clock, and its `score` remains null until close.

Closing, performed by the buyer, requires the logical clock to have reached the `response_deadline` (otherwise `ERR_SOLICITATION_DEADLINE_NOT_PASSED`) and moves the solicitation to `CLOSED`. Closing freezes the scoring inputs and computes a `score` for every quote on the solicitation — including any already `DISQUALIFIED`, although those are excluded from the eligible pool. When no quote is eligible at close there is no lowest price, and every quote's `score` remains null. The price component of a quote is one hundred multiplied by the lowest `price_cents` among the quotes eligible at close — meaning `SUBMITTED` with an `ACTIVE` vendor at that moment, a pinning that is never re-derived later — divided by the quote's own `price_cents`. A quote earns one hundred diversity points when its vendor's `diversity_certification` is anything other than `NONE`, and zero otherwise. Sustainability points are one hundred for a `GOLD` vendor, sixty for `SILVER`, thirty for `BRONZE`, and zero for `NONE`. The final score is seventy percent of the price component, plus twenty percent of the diversity points, plus ten percent of the sustainability points, rounded half up to exactly two decimal places with the rounding applied once at the end.

Award belongs to the `ProcurementDirector` and requires a `CLOSED` solicitation (otherwise `ERR_SOLICITATION_NOT_CLOSED`). The eligible pool at award consists of quotes still `SUBMITTED` whose vendor is `ACTIVE`; an empty pool rejects the award with `ERR_NO_ELIGIBLE_QUOTES`. If the pool holds fewer quotes than the solicitation's `min_quotes`, the award proceeds only when an `override_reason` is documented, and is rejected with `ERR_INSUFFICIENT_QUOTES` otherwise. The computed winner is the eligible quote with the highest score, ties broken first by the earliest `submitted_at` and then by the earliest `created_at` — the quote `id` is never consulted. The director may award a different quote by passing its `quote_id`, but only with an `override_reason`; diverging from the computed winner without one is rejected with `ERR_AWARD_NOT_TOP_SCORE`, and naming a quote that is not in the eligible pool is rejected with `ERR_AWARD_NOT_TOP_SCORE` even when an `override_reason` is documented. On award the winning quote becomes `AWARDED`, every other `SUBMITTED` quote becomes `NOT_AWARDED`, `awarded_quote_id` and `awarded_at` are stamped, and — critically for the pipeline — the requisition's `vendor_id` is set to the winning quote's vendor and its `sourcing_method` becomes `COMPETITIVE_BID`. A buyer may instead cancel an `OPEN` or `CLOSED` solicitation outright (from any other status, `ERR_SOLICITATION_NOT_CANCELLABLE`), which moves all its `SUBMITTED` quotes to `NOT_AWARDED`; an `AWARDED` solicitation reaches `CANCELLED` only through the vendor-suspension cascade of §3.1.

### 3.5. Purchase Orders and Receiving

Once a requisition stands `APPROVED`, a `Buyer` issues its **purchase order**. Issuance from any other status is rejected with `ERR_REQUISITION_NOT_APPROVED`. No vendor needs to be designated on the requisition at this point — the sourcing gate lives at the `PURCHASING` approval step — and a vendor-less requisition issues an order whose `vendor_id` is null. When the requisition rides a contract, the contract must still be `EXECUTED` (otherwise `ERR_CONTRACT_NOT_EXECUTED`) with the logical clock inside the half-open effective period — on or after `effective_start` and strictly before `effective_end` (otherwise `ERR_CONTRACT_EXPIRED`). Issuance creates the purchase order with a sequential `po_number` in the `PO-000001` format; a `lines` array pinned as an exact copy of the requisition's lines, each carrying its `line_no`; `vendor_id`, `contract_id`, and `grant_id` copied from the requisition (any of the three null when absent); a `total_cents` summed over the pinned lines; `charge_cents` copied from the requisition, this being the amount the grant ledger will settle upon payment; `contract_version_pinned` recording the contract's `version` observed at issue, null for contract-free orders; and `issued_at` stamped from the logical clock. The requisition advances to `PO_ISSUED`, a terminal status for it, while the grant encumbrance itself is unchanged — conceptually the encumbrance simply transfers from the approved requisition to the now-outstanding purchase order.

A purchase order carries two independent status dimensions. Its `fulfillment_status` begins at `ISSUED` and is driven purely by receipts; its `match_status` is derived from invoices and cascades — `UNMATCHED` while no invoice exists, `EXCEPTION` while any invoice stands in `EXCEPTION` or the `contract_terminated_flag` (initially false) is set, `MATCHED` when at least one invoice is `PAYABLE` or `PAID` and none is in `EXCEPTION`, and `CLOSED` once the order is `CANCELLED`. Receipts mutate only fulfillment; invoices and contract cascades mutate only match posture — with one exception noted below.

Receiving is clerical and incremental. A `ReceivingClerk` posts a receipt against an order whose fulfillment is `ISSUED` or `PARTIALLY_RECEIVED` — anything else is rejected with `ERR_PO_NOT_RECEIVABLE` — supplying `lines` of `line_no` and `quantity`, each quantity strictly positive and every `line_no` present on the pinned order lines (otherwise `ERR_INVALID_REQUEST`). Per line, the cumulative quantity across all `POSTED` receipts plus the new quantity may not exceed the ordered quantity, or the posting fails with `ERR_OVER_RECEIPT`. Each posted receipt records its `po_id` binding to the order, the clerk's `received_by` identity, and a `received_at` from the logical clock, and fulfillment is then recomputed: `FULLY_RECEIVED` exactly when every line's cumulative posted quantity equals its ordered quantity, otherwise `PARTIALLY_RECEIVED`. Both `FULLY_RECEIVED` and `CANCELLED` are terminal for fulfillment.

A clerk may void a `POSTED` receipt, moving it to the terminal `VOIDED` status — voiding anything else is `ERR_RECEIPT_NOT_VOIDABLE` — and this is the one operation that touches both dimensions. Fulfillment is recomputed from the remaining `POSTED` receipts, dropping all the way back to `ISSUED` when none remain (and from `FULLY_RECEIVED` back to `PARTIALLY_RECEIVED` when some but not all lines stay complete). Then every invoice on the order still `PAYABLE` is re-matched, and if any line's invoiced quantity now exceeds the cumulative posted received quantity, that invoice drops to `EXCEPTION` with `exception_reason` `RECEIPT_VOIDED`.

An order may be cancelled by a buyer only while it is `ISSUED` with no `POSTED` receipts and no invoices at all — otherwise `ERR_PO_NOT_CANCELLABLE`. Cancellation moves fulfillment to `CANCELLED` and match posture to `CLOSED`, releases the grant encumbrance by subtracting the order's `charge_cents` when it is grant-funded, and returns the source requisition from `PO_ISSUED` to `APPROVED` so that issuance can be attempted again.

### 3.6. Invoicing, the Three-Way Match, and Settlement

An `APClerk` records a supplier **invoice** against a purchase order by providing the supplier's `invoice_number` and `lines` of `line_no`, `quantity`, and `unit_price_cents`. The order must not be `CANCELLED` (otherwise `ERR_PO_NOT_INVOICABLE`), and it must not already carry an open invoice in `PAYABLE` or `EXCEPTION`, nor a `PAID` one — invoicing is closed in either case with `ERR_PO_INVOICING_CLOSED`. Every `line_no` on the invoice must exist on the pinned order lines (otherwise `ERR_INVOICE_LINE_UNKNOWN`). The invoice's `vendor_id` is copied from the order, its `total_cents` is the exact integer sum over its lines of quantity times unit price, and the three-way match runs immediately at creation.

The match is deterministic. If the order has no `POSTED` receipts at all, the invoice is born in `EXCEPTION` with `exception_reason` `NO_RECEIPT` and evaluation stops there, leaving both totals at zero. Otherwise each invoice line is examined in ascending `line_no` order. The received quantity for a line is the sum of quantities for that line number across all `POSTED` receipts — voided receipts never count — and an invoiced quantity exceeding it fails the line for quantity. Independently, the line's price variance is the absolute difference between the invoice line's `unit_price_cents` and the pinned order line's `unit_price_cents`, multiplied by the invoiced quantity; and the line's tolerance is two percent of the order line's `unit_price_cents` multiplied by the invoiced quantity, rounded half up to whole cents — each line's tolerance is rounded before any summation takes place. A line whose variance exceeds its own tolerance fails for price. The invoice's `total_variance_cents` is the sum of all per-line variances — zero whenever evaluation never reached pricing — and its `total_tolerance_cents` is the sum of the already-rounded per-line tolerances. Even when no individual line fails, if the aggregate variance exceeds the aggregate tolerance the invoice is an `EXCEPTION` for price. A single `exception_reason` is recorded by precedence: `NO_RECEIPT` first, then `QTY_OVER_RECEIPT`, then `PRICE_VARIANCE`; when several lines fail under the same reason, the lowest failing line number decides. A clean invoice lands in `PAYABLE` with `exception_reason` `NONE`. Whichever way it lands, the order's match posture is recomputed.

An invoice in `EXCEPTION` is resolved by an accounts payable clerk who is not the requester of the funding requisition — a resolver whose `X-User-ID` equals that `requester_id` is refused with `ERR_SELF_RESOLUTION_FORBIDDEN` — and resolution from any status other than `EXCEPTION` is `ERR_INVOICE_NOT_RESOLVABLE`. The resolution `action` is either `ACCEPT_VARIANCE` or `REJECT_INVOICE`, with an optional `comment`. Accepting the variance re-runs the three-way match against the current `POSTED` receipts and pinned order prices; only if the re-match passes does the invoice move to `PAYABLE`, recording the resolver in `variance_accepted_by`, otherwise it stays in `EXCEPTION`. Either way the re-match refreshes the invoice's `total_variance_cents`, `total_tolerance_cents`, and `exception_reason`. Rejecting terminates the invoice as `REJECTED`, which reopens the order for a fresh invoice. Either way the order's match posture recomputes.

Payment, also by an `APClerk`, requires a `PAYABLE` invoice (otherwise `ERR_INVOICE_NOT_PAYABLE`) and is terminal: the invoice becomes `PAID`, `paid_at` is stamped from the logical clock — the timestamp later used by paid-basis diversity reporting — and the order's match posture recomputes to `MATCHED`. When the order is grant-funded, payment is the settlement event for the grant ledger: the order's `charge_cents` leaves `encumbered_cents` and enters `spent_cents`.

### 3.7. The P-Card Program: Issuance, Limits, and Transactions

A `ProcurementAdmin` issues a **P-card** to a department, supplying `department_id`, the `cardholder_name`, a `single_txn_limit_cents` ceiling per debit, a `monthly_limit_cents` ceiling per statement cycle, and `allowed_mccs`, an array of permitted merchant category codes — an empty array means the card is unrestricted by merchant category. The single-transaction limit may not exceed the monthly limit; an inconsistent pair is rejected with `ERR_LIMIT_INCONSISTENT`, both at issuance and on any later limits change. A new card is `ACTIVE` with `cycle_index` zero, `consecutive_unreconciled_cycles` zero, and zero utilization. The card's `id` doubles as the cardholder's identity: when a `Cardholder` acts, `X-User-ID` must equal that `id`, and any cardholder operation on another card is refused with `ERR_NOT_RESOURCE_OWNER`.

Limits evolve through a guarded limits change carrying `expected_pcard_version` plus any subset of `single_txn_limit_cents`, `monthly_limit_cents`, or `allowed_mccs` — any subset is accepted, including none, and a null `allowed_mccs` leaves the list unchanged; a stale version is rejected with `ERR_STALE_VERSION`, and a successful change increments the card's `version`. A temporary elevation of the single-transaction limit is scheduled separately, as described in §3.8; at any moment at most one elevation window can be in force, so when a debit is posted the effective single-transaction limit is the `elevated_single_txn_limit_cents` of the unique `SCHEDULED` elevation whose half-open window contains the logical clock — `window_start` inclusive, `window_end` exclusive — and otherwise the card's own `single_txn_limit_cents`. A debit timestamped exactly at `window_start` already enjoys the elevated limit; one timestamped exactly at `window_end` falls back to the base limit.

Transactions are posted by the cardholder with an `amount_cents` that must be strictly positive for either `entry_type`, an `entry_type` of `DEBIT` or `CREDIT` (a credit being a merchant refund), a free-text `merchant_name` — deliberately not a vendor reference — and an `mcc_code`. When the card's `allowed_mccs` is non-empty, a code outside it is rejected with `ERR_MCC_NOT_ALLOWED`. Posting requires the card to be `ACTIVE`: a suspended card rejects with `ERR_CARD_NOT_ACTIVE`, and a closed one with `ERR_CARD_CLOSED`. Two inclusive money gates then apply to debits: the amount may not exceed the effective single-transaction limit (otherwise `ERR_SINGLE_TXN_LIMIT_EXCEEDED`), and the current `utilization_cents` plus the new amount may not exceed `monthly_limit_cents` — equality is allowed on both (otherwise `ERR_MONTHLY_LIMIT_EXCEEDED`). A posted debit starts in `POSTED`; a posted credit starts directly in `RECONCILED`. Both capture `posted_at` from the logical clock and the card's current `cycle_index` at posting.

The card's `utilization_cents` is the sum of `amount_cents` over its debits in the current cycle whose status is `POSTED`, `RECONCILED`, or `DISPUTED`, minus the corresponding sum over credits in the current cycle that have not been `REVERSED`. Disputed debits deliberately remain inside utilization; reversed transactions leave it entirely; refunds reduce it, so utilization may legitimately go negative. `available_credit_cents` is always the monthly limit minus the utilization, and the two figures always sum back to `monthly_limit_cents`.

### 3.8. Statement Cycles, Reconciliation, Disputes, and Elevation Windows

Reconciliation is the cardholder's monthly duty. A `POSTED` transaction — reconciling anything else is `ERR_TXN_NOT_RECONCILABLE` — is reconciled with a non-empty `receipt_reference` (a missing one is `ERR_INVALID_REQUEST`), an `allocation_type` of `GENERAL` or `GRANT`, and, for grant allocations, a `grant_id` and a `cost_category`. For a `GENERAL` allocation any client-supplied `grant_id` or `cost_category` is ignored and both are stored null. The card must not be `CLOSED` (`ERR_CARD_CLOSED`), and only the card's own holder may reconcile (`ERR_NOT_RESOURCE_OWNER`). A grant allocation re-runs the sponsor's allowability gauntlet: the grant must exist and be `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`), the `cost_category` must appear in its `allowed_categories` (otherwise `ERR_GRANT_CATEGORY_NOT_ALLOWABLE`), the logical clock must lie inside the inclusive budget period (otherwise `ERR_GRANT_BUDGET_PERIOD_EXPIRED`), and the grant's `provisional_remaining_cents` must cover the transaction's `amount_cents` (otherwise `ERR_GRANT_BUDGET_EXCEEDED`, HTTP 402). Success records the receipt reference, allocation fields, and `reconciled_at`, moves the transaction to `RECONCILED`, and — for grant allocations — adds the amount to the grant's `spent_cents` immediately.

Disputes travel in both directions. The cardholder may dispute a transaction in `POSTED` or `RECONCILED` — any other status is `ERR_TXN_NOT_DISPUTABLE`, a closed card blocks the operation with `ERR_CARD_CLOSED`, and ownership is enforced as everywhere — supplying a `reason`, which is accepted but not recorded. The transaction becomes `DISPUTED` and remembers where it came from in `pre_dispute_status` (`POSTED` or `RECONCILED`); utilization is untouched, since disputed debits remain inside it. A `ProcurementAdmin` then resolves the dispute — resolution requires a `DISPUTED` transaction, else `ERR_TXN_NOT_DISPUTED` — with an `outcome`. `CARDHOLDER_FAVOR` reverses the transaction into the terminal `REVERSED` status: its amount leaves utilization, and if the transaction had been reconciled to a grant before the dispute, the same amount is compensated out of that grant's `spent_cents`. `MERCHANT_FAVOR` restores the transaction to its `pre_dispute_status` — a formerly posted transaction returns to `POSTED` and still awaits reconciliation, a formerly reconciled one returns to `RECONCILED` — and `pre_dispute_status` is cleared on either outcome.

Elevation windows are the program's pressure valve for one-off large purchases. A `ProcurementAdmin` schedules one on a card with an `elevated_single_txn_limit_cents`, a `window_start`, and a `window_end`, the start strictly before the end on pain of `ERR_INVALID_REQUEST`. Scheduling is refused only on a `CLOSED` card (`ERR_CARD_CLOSED`); a `SUSPENDED` card accepts new windows. Windows on the same card may never overlap an existing `SCHEDULED` elevation (`ERR_ELEVATION_OVERLAP`) and must keep at least a seven-day gap from any adjacent `SCHEDULED` one (`ERR_ELEVATION_GAP_VIOLATION`). An elevation is born `SCHEDULED` and ends `CANCELLED` — there is deliberately no expired state, because effectiveness is evaluated against the clock at posting time. The administrator may cancel a scheduled elevation directly (from any other status, `ERR_ELEVATION_STATE_INVALID`), and suspension or closure of the card cancels every scheduled elevation on it as a cascade.

Card administration itself is straightforward but guarded. A `ProcurementAdmin` suspends an `ACTIVE` card, reinstates a `SUSPENDED` one — which resets `consecutive_unreconciled_cycles` to zero — or closes a card from either non-terminal state; each attempted from the wrong state is `ERR_CARD_STATE_INVALID`. Closing additionally requires that no transaction remain in `POSTED` or `DISPUTED` (otherwise `ERR_CARD_HAS_OPEN_TRANSACTIONS`), and `CLOSED` is terminal: every card mutation on a closed card is refused with `ERR_CARD_CLOSED`. On reconcile and dispute the transaction-state guard fires first, so `ERR_CARD_CLOSED` surfaces only when the transaction is otherwise actionable (`POSTED` for reconcile, `POSTED` or `RECONCILED` for dispute).

The statement cycle closes through an operations-run checkpoint run by the administrator. The checkpoint runs on an `ACTIVE` or `SUSPENDED` card and is refused on a `CLOSED` one with `ERR_CARD_CLOSED`. The system counts the debits of the closing cycle whose status is `POSTED` or `DISPUTED`. If any exist, the card's `consecutive_unreconciled_cycles` increments by one; a clean cycle resets it to zero. When the counter reaches two — the threshold is inclusive — the card is automatically suspended and its scheduled elevations are cancelled in the same cascade as a manual suspension. The checkpoint then increments `cycle_index`, opening a new cycle; transactions of the old cycle leave the utilization base from that moment.

### 3.9. Surplus Property: Redistribution, Sale, and the Proceeds Waterfall

The lifecycle of university property ends here. A `SurplusManager` declares a **surplus asset** with its `asset_tag`, the owning `department_id`, a `description`, a `condition` of `NEW`, `GOOD`, `FAIR`, or `POOR`, an `estimated_value_cents` that will drive both the sale floor and the high-value role gate, and an optional `disposal_cost_cents` defaulting to zero. Declaration stamps `declared_at` from the logical clock and opens a redistribution window that runs from `declared_at` up to — but not including — ten days later.

During that window, any `Requester` may claim the asset for another department by naming a `claiming_department_id`. Claiming requires the asset still `DECLARED` (otherwise `ERR_SURPLUS_NOT_CLAIMABLE`), the logical clock still inside the window — at or after the window's end the claim fails with `ERR_REDISTRIBUTION_WINDOW_EXPIRED` — and a claimant different from the owning department (otherwise `ERR_SELF_CLAIM_FORBIDDEN`). A successful claim moves the asset to `TRANSFERRED`, records the claiming department, and creates no proceeds.

Once the window has fully elapsed, the manager lists the asset for sale; listing still-`DECLARED` stock is required (otherwise `ERR_SURPLUS_NOT_LISTABLE`), and listing before the window ends is rejected with `ERR_REDISTRIBUTION_WINDOW_ACTIVE`. A `LISTED` asset may then be sold, donated, or scrapped. Selling accepts a `sale_price_cents` and an optional `buyer_name`, and is guarded twice: the price must clear a floor of 2,500 cents or forty percent of `estimated_value_cents` rounded half up to whole cents, whichever is greater — a price exactly equal to the floor is accepted, and anything below it is rejected with `ERR_SALE_PRICE_BELOW_FLOOR`; and when the estimated value is at least 5,000,000 cents (50,000 dollars), only the `ProcurementDirector` may complete the sale — a `SurplusManager` attempting it receives `ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR` rather than a generic role error. A successful sale becomes `SOLD`, records the price and buyer, and computes the proceeds waterfall in a pinned order: first, cost recovery returns `min(disposal_cost_cents, sale_price_cents)` into `proceeds_cost_recovery_cents`; second, the department's share is half of what remains after cost recovery, rounded half up to whole cents, stored in `proceeds_dept_share_cents`; third, the central share takes the entire remainder into `proceeds_central_share_cents`, so the rounding remainder lands centrally and the three buckets always sum back to the sale price. Donation instead requires a non-empty `recipient_name`, which it records, requires a `LISTED` asset (otherwise `ERR_SURPLUS_NOT_DONATABLE`), and produces no proceeds. Scrapping is available from either `DECLARED` or `LISTED` (otherwise `ERR_SURPLUS_NOT_SCRAPPABLE`), accepts an optional `reason` that is not recorded, and ends the asset as `SCRAPPED`. All four outcomes — `TRANSFERRED`, `SOLD`, `DONATED`, and `SCRAPPED` — are terminal.

### 3.10. Supplier-Diversity and Sustainability Reporting

The program closes the loop on its goals with a computed per-department report, available to any authenticated role, that measures diverse-supplier spend on two bases selected by the `basis` parameter. On the `COMMITTED` basis — the default — the report sums `total_cents` over the department's purchase orders whose fulfillment is anything other than `CANCELLED`, and again over the same set restricted to vendors whose `diversity_certification` is anything other than `NONE`; on the `PAID` basis it sums `total_cents` over paid invoices whose purchase order belongs to the department, with the same diverse-vendor restriction. An unrecognized `basis` is rejected with `ERR_INVALID_REQUEST`. Each basis counts everything up to the logical clock — committed spend is bounded by `issued_at`, paid spend by `paid_at` — and the optional `window_start` and `window_end` parameters apply inclusive bounds on those same timestamps; the logical-clock upper bound always applies, even when a window is supplied, so the window bounds only narrow it further, and the two window bounds are not cross-validated against each other. The response reports the `basis`, both totals as `diverse_spend_cents` and `total_spend_cents`, a `ratio` equal to the diverse spend divided by the total spend rounded half up to exactly four decimal places — defined as 0.0000 when the total spend is zero — and `goal_met`, true exactly when the ratio reaches the department's `diversity_goal_pct`. The two bases legitimately diverge: the committed basis counts orders at issue regardless of payment, while the paid basis counts invoices only once paid, so identical underlying purchases yield different ratios until invoices settle.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Operations that create a new resource — a department, vendor, grant, contract, amendment draft, requisition, solicitation, quote, purchase order, receipt, invoice, P-card, elevation, transaction, or surplus asset — return `201 Created`; operations that modify an existing resource in place, including all state transitions, returns, approvals, and checkpoint runs, return `200 OK`. Request payloads, preconditions, side effects, and error codes are specified per workflow in §3; the table below is the navigational index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ProcurementAdmin |
| POST | `/departments` | Create a department | ProcurementAdmin |
| GET | `/departments` | List departments | Any |
| GET | `/departments/{id}` | Get a department | Any |
| GET | `/departments/{id}/diversity-report` | Supplier-diversity spend report (committed or paid basis) | Any |
| POST | `/vendors` | Create a vendor | Buyer |
| GET | `/vendors` | List vendors | Any |
| GET | `/vendors/{id}` | Get a vendor | Any |
| GET | `/vendors/{id}/quotes` | List quotes submitted by a vendor | Any |
| POST | `/vendors/{id}/suspend` | Suspend a vendor (cascade) | ProcurementAdmin |
| POST | `/vendors/{id}/reinstate` | Reinstate a suspended vendor | ProcurementAdmin |
| POST | `/grants` | Create a grant | GrantOfficer |
| GET | `/grants` | List grants | Any |
| GET | `/grants/{id}` | Get a grant (with computed ledger fields) | Any |
| GET | `/grants/{id}/budget-ledger` | Computed grant budget ledger (both remaining variants) | Any |
| POST | `/grants/{id}/suspend` | Suspend a grant | GrantOfficer |
| POST | `/grants/{id}/reinstate` | Reinstate a suspended grant | GrantOfficer |
| POST | `/grants/{id}/close` | Close a grant (requires zero encumbrance) | GrantOfficer |
| POST | `/contracts` | Create a contract in DRAFT | ContractOfficer |
| GET | `/contracts` | List contracts | Any |
| GET | `/contracts/{id}` | Get a contract | Any |
| POST | `/contracts/{id}/submit-review` | Move DRAFT or IN_NEGOTIATION contract to UNDER_REVIEW | ContractOfficer |
| POST | `/contracts/{id}/negotiate` | Open a negotiation round (round increments) | ContractOfficer |
| POST | `/contracts/{id}/approve-review` | Approve the review | ContractOfficer |
| POST | `/contracts/{id}/execute` | Execute an approved contract (exclusivity, supersede) | ProcurementDirector |
| POST | `/contracts/{id}/amend` | Create an amendment draft (OCC-guarded) | ContractOfficer |
| POST | `/contracts/{id}/terminate` | Terminate an EXECUTED contract (cascade) | ProcurementDirector |
| POST | `/requisitions` | Create a requisition in DRAFT | Requester |
| GET | `/requisitions` | List requisitions with filters | Any |
| GET | `/requisitions/{id}` | Get a requisition | Any |
| PATCH | `/requisitions/{id}` | Edit a DRAFT or RETURNED requisition (OCC-guarded, owner-only) | Requester |
| POST | `/requisitions/{id}/submit` | Submit for approval (chain snapshot, charge, anti-split) | Requester |
| POST | `/requisitions/{id}/approve-step` | Approve the current chain step | DepartmentApprover, GrantOfficer, Buyer, ProcurementDirector, ContractOfficer |
| POST | `/requisitions/{id}/return-step` | Return the requisition to the requester | DepartmentApprover, GrantOfficer, Buyer, ProcurementDirector, ContractOfficer |
| POST | `/requisitions/{id}/cancel` | Cancel from DRAFT, RETURNED, or APPROVED | Requester |
| GET | `/requisitions/{id}/approvals` | List the approval audit trail (chronological) | Any |
| POST | `/requisitions/{id}/solicitations` | Open a competitive solicitation for a requisition | Buyer |
| GET | `/requisitions/{id}/solicitations` | List solicitations of a requisition | Any |
| GET | `/solicitations/{id}` | Get a solicitation | Any |
| POST | `/solicitations/{id}/quotes` | Submit a vendor quote while OPEN before the deadline | Buyer |
| GET | `/solicitations/{id}/quotes` | List quotes of a solicitation | Any |
| POST | `/solicitations/{id}/close` | Close the solicitation at/after the deadline (scores quotes) | Buyer |
| POST | `/solicitations/{id}/award` | Award to the computed winner (or documented override) | ProcurementDirector |
| POST | `/solicitations/{id}/cancel` | Cancel an OPEN or CLOSED solicitation | Buyer |
| POST | `/requisitions/{id}/issue-po` | Issue a PurchaseOrder from an APPROVED requisition | Buyer |
| GET | `/purchase-orders` | List purchase orders with filters | Any |
| GET | `/purchase-orders/{id}` | Get a purchase order | Any |
| POST | `/purchase-orders/{id}/cancel` | Cancel an unreceived, uninvoiced PO (releases encumbrance) | Buyer |
| POST | `/purchase-orders/{id}/receipts` | Post a (partial) receipt against PO lines | ReceivingClerk |
| GET | `/purchase-orders/{id}/receipts` | List receipts of a PO | Any |
| POST | `/receipts/{id}/void` | Void a posted receipt (recomputes fulfillment; re-matches invoices) | ReceivingClerk |
| POST | `/purchase-orders/{id}/invoices` | Create an invoice (three-way match runs immediately) | APClerk |
| GET | `/purchase-orders/{id}/invoices` | List invoices of a PO | Any |
| GET | `/invoices` | List invoices with filters | Any |
| GET | `/invoices/{id}` | Get an invoice | Any |
| POST | `/invoices/{id}/resolve-exception` | Resolve an EXCEPTION invoice (accept variance or reject) | APClerk |
| POST | `/invoices/{id}/pay` | Pay a PAYABLE invoice (settles grant charge) | APClerk |
| POST | `/pcards` | Issue a P-card | ProcurementAdmin |
| GET | `/pcards` | List P-cards | Any |
| GET | `/pcards/{id}` | Get a P-card (with utilization and available credit) | Any |
| PATCH | `/pcards/{id}/limits` | Change card limits / MCC list (OCC-guarded) | ProcurementAdmin |
| POST | `/pcards/{id}/suspend` | Suspend a card (cancels scheduled elevations) | ProcurementAdmin |
| POST | `/pcards/{id}/reinstate` | Reinstate a suspended card (resets aging counter) | ProcurementAdmin |
| POST | `/pcards/{id}/close` | Close a card (requires no open transactions) | ProcurementAdmin |
| POST | `/pcards/{id}/close-cycle` | Close the statement cycle (aging, escalation, new cycle) | ProcurementAdmin |
| POST | `/pcards/{id}/elevations` | Schedule a temporary limit elevation window | ProcurementAdmin |
| GET | `/pcards/{id}/elevations` | List elevations of a card | Any |
| POST | `/pcard-elevations/{id}/cancel` | Cancel a scheduled elevation | ProcurementAdmin |
| POST | `/pcards/{id}/transactions` | Post a transaction (DEBIT gated by MCC and limits) | Cardholder |
| GET | `/pcards/{id}/transactions` | List transactions of a card | Any |
| GET | `/pcard-transactions` | List transactions with filters | Any |
| GET | `/pcard-transactions/{id}` | Get a transaction | Any |
| POST | `/pcard-transactions/{id}/reconcile` | Reconcile a POSTED transaction (receipt + allocation) | Cardholder |
| POST | `/pcard-transactions/{id}/dispute` | Dispute a POSTED or RECONCILED transaction | Cardholder |
| POST | `/pcard-transactions/{id}/resolve-dispute` | Resolve a dispute (cardholder or merchant favor) | ProcurementAdmin |
| POST | `/surplus-assets` | Declare a surplus asset (opens redistribution window) | SurplusManager |
| GET | `/surplus-assets` | List surplus assets | Any |
| GET | `/surplus-assets/{id}` | Get a surplus asset | Any |
| POST | `/surplus-assets/{id}/claim` | Claim an asset for another department in the window | Requester |
| POST | `/surplus-assets/{id}/list-for-sale` | List an unclaimed asset after the window | SurplusManager |
| POST | `/surplus-assets/{id}/sell` | Sell a listed asset (floor price; waterfall) | SurplusManager, ProcurementDirector |
| POST | `/surplus-assets/{id}/donate` | Donate a listed asset | SurplusManager |
| POST | `/surplus-assets/{id}/scrap` | Scrap a declared or listed asset | SurplusManager |

## 5. Error Code Catalogue

Trigger conditions for every error live in the workflow narratives of §2 and §3; this table is the index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_SOLICITATION_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_PO_NOT_FOUND` | 404 Not Found |
| `ERR_RECEIPT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_PCARD_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_ELEVATION_NOT_FOUND` | 404 Not Found |
| `ERR_SURPLUS_ASSET_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REQUISITION_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_REQUISITION_NOT_EDITABLE` | 409 Conflict |
| `ERR_REQUISITION_NOT_IN_APPROVAL` | 409 Conflict |
| `ERR_REQUISITION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REQUISITION_NOT_APPROVED` | 409 Conflict |
| `ERR_APPROVAL_STEP_MISMATCH` | 409 Conflict |
| `ERR_CONTRACT_STATE_INVALID` | 409 Conflict |
| `ERR_SOLICITATION_NOT_OPEN` | 409 Conflict |
| `ERR_SOLICITATION_NOT_CLOSED` | 409 Conflict |
| `ERR_SOLICITATION_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PO_NOT_RECEIVABLE` | 409 Conflict |
| `ERR_PO_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_PO_NOT_INVOICABLE` | 409 Conflict |
| `ERR_PO_INVOICING_CLOSED` | 409 Conflict |
| `ERR_RECEIPT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_CARD_STATE_INVALID` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARD_CLOSED` | 409 Conflict |
| `ERR_CARD_HAS_OPEN_TRANSACTIONS` | 409 Conflict |
| `ERR_TXN_NOT_RECONCILABLE` | 409 Conflict |
| `ERR_TXN_NOT_DISPUTABLE` | 409 Conflict |
| `ERR_TXN_NOT_DISPUTED` | 409 Conflict |
| `ERR_SURPLUS_NOT_CLAIMABLE` | 409 Conflict |
| `ERR_SURPLUS_NOT_LISTABLE` | 409 Conflict |
| `ERR_SURPLUS_NOT_SELLABLE` | 409 Conflict |
| `ERR_SURPLUS_NOT_DONATABLE` | 409 Conflict |
| `ERR_SURPLUS_NOT_SCRAPPABLE` | 409 Conflict |
| `ERR_GRANT_STATE_INVALID` | 409 Conflict |
| `ERR_VENDOR_STATE_INVALID` | 409 Conflict |
| `ERR_ELEVATION_STATE_INVALID` | 409 Conflict |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_RESOLUTION_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_CLAIM_FORBIDDEN` | 403 Forbidden |
| `ERR_GRANT_CATEGORY_NOT_ALLOWABLE` | 422 Unprocessable Entity |
| `ERR_GRANT_BUDGET_PERIOD_EXPIRED` | 422 Unprocessable Entity |
| `ERR_MCC_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_SOLE_SOURCE_JUSTIFICATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SOLICITATION_EXPIRED` | 409 Conflict |
| `ERR_SOLICITATION_DEADLINE_NOT_PASSED` | 409 Conflict |
| `ERR_CONTRACT_EXPIRED` | 409 Conflict |
| `ERR_REDISTRIBUTION_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_REDISTRIBUTION_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_BID_SPLITTING_DETECTED` | 409 Conflict |
| `ERR_CONTRACT_OVERLAP` | 409 Conflict |
| `ERR_ELEVATION_OVERLAP` | 409 Conflict |
| `ERR_ELEVATION_GAP_VIOLATION` | 409 Conflict |
| `ERR_DUPLICATE_QUOTE` | 409 Conflict |
| `ERR_SOURCING_REQUIRED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_QUOTES` | 409 Conflict |
| `ERR_INSUFFICIENT_QUOTES` | 409 Conflict |
| `ERR_AWARD_NOT_TOP_SCORE` | 409 Conflict |
| `ERR_OVER_RECEIPT` | 422 Unprocessable Entity |
| `ERR_INVOICE_LINE_UNKNOWN` | 422 Unprocessable Entity |
| `ERR_LIMIT_INCONSISTENT` | 422 Unprocessable Entity |
| `ERR_GRANT_HAS_OPEN_ENCUMBRANCES` | 409 Conflict |
| `ERR_SOLICITATION_NOT_ALLOWED` | 409 Conflict |
| `ERR_SOLICITATION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_VENDOR_SUSPENDED` | 409 Conflict |
| `ERR_GRANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_EXECUTED` | 409 Conflict |
| `ERR_APPROVER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_GRANT_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_SINGLE_TXN_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MONTHLY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SALE_PRICE_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
