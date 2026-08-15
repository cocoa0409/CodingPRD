# Import Buying Agent API — Product Requirements Document

## 1. Introduction

Retail and consumer brands rarely run their own overseas sourcing offices. Instead they engage a **buying agent**: an intermediary firm that identifies candidate factories, scores their quality systems, brokers samples, negotiates price and lead time, books orders against factory capacity, tracks production through milestones and inspections, and — when things go wrong — files quality claims and claws money back from the factory. The agent's fee is a commission on the orders it brokers, computed on a tiered rate that rewards brokers who move more volume through the platform in a calendar year.

This document specifies the HTTP API that backs such a buying-agent platform. It is the single authoritative reference for the platform's domain model, state machines, calculation rules, validation ordering, and endpoint surface. The API serves five external constituencies — buyers, the agent firm's own sourcing agents, factory representatives, third-party inspectors, and compliance officers — plus a platform operator who bootstraps the actors and drives a logical test clock. Several workflows (quotation negotiation, milestone tracking, chargeback cascading) deliberately enforce segregation of duties: the agent who owns an order is not allowed to adjudicate claims against it, and a factory cannot grade its own audit.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying either header as the empty string, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role named in `X-User-Role` is not in the endpoint's permitted role list, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

When listing or creating child resources against a `PurchaseOrder` (milestones, inspections, shipments, quality claims), the parent's id appears in the URL path as the `po_id` segment; the server validates it as the parent before any child lookup.

The platform recognizes exactly six role names, spelled as follows:

- `PlatformAdmin` — platform operator; bootstraps buyers, agents, and inspectors, and drives the logical test clock. `X-User-ID` is an opaque operator identifier, not tied to any persisted entity.
- `BuyerManager` — buyer-side manager; owns sourcing requests, reviews samples, negotiates and accepts quotations, files quality claims, and confirms receipts. When `X-User-Role` is `BuyerManager`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks against any resource that references a `Buyer` compare the resource's `buyer_id` to `X-User-ID`.
- `SourcingAgent` — buying-agent employee; identifies factories, conducts audits, uploads compliance documents, manages samples, milestones, inspections, and shipments, and adjudicates claims on other agents' purchase orders. When `X-User-Role` is `SourcingAgent`, `X-User-ID` is the `id` of the acting `Agent`; ownership checks compare the resource's `assigned_agent_id` (or, for factory-scoped children, the factory's agent chain) to `X-User-ID`.
- `FactoryRep` — factory representative; submits quotations, counter-offers, milestone evidence, and shipping document handover. When `X-User-Role` is `FactoryRep`, `X-User-ID` is the `id` of the acting `Factory`; ownership checks compare the resource's `factory_id` to `X-User-ID`.
- `Inspector` — third-party inspector; records AQL results only on inspections assigned to that inspector. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; ownership checks compare the inspection's `inspector_id` to `X-User-ID`.
- `ComplianceOfficer` — compliance authority; approves or rejects audits and verifies or rejects compliance documents; never touches the commercial flow. `X-User-ID` is an opaque operator identifier, not tied to any persisted entity.

Ownership scoping (`BuyerManager` checks `buyer_id`, `SourcingAgent` checks `assigned_agent_id`, `FactoryRep` checks `factory_id`, `Inspector` checks `inspector_id`) is enforced on every role-scoped write endpoint. A violation is rejected with `ERR_OWNERSHIP_SCOPE_VIOLATION` (HTTP 403). The two opaque-identity roles (`PlatformAdmin`, `ComplianceOfficer`) bypass ownership checks because they act on the platform as a whole rather than on owned sub-resources.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format:

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

A request that matches no route is rejected with `ERR_NOT_FOUND` (HTTP 404); a known path called with an unsupported method is rejected with `ERR_VALIDATION` (HTTP 405); an unexpected server failure yields `ERR_INTERNAL` (HTTP 500).

### 2.3. Pagination

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. Out-of-range values are clamped, not rejected: a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0; a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION` (HTTP 400). List results are sorted by `created_at` ascending, with ties broken by creation order (earliest-created first). The response `meta` block includes `limit`, `offset`, `total_count`, and `has_more` so the client can page deterministically.

### 2.4. Common Resource Properties

Every persisted entity carries the following system-managed fields, unless explicitly noted otherwise:

- `id` — a server-minted UUID with no type prefix, returned as a string.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set at creation. All server-stamped timestamps (including `updated_at`, `approved_at`, `delivered_at`, and the envelope's `api_request_timestamp`) are taken from the §2.5 logical clock, never from wall-clock time, so entities created or mutated at the same logical instant carry identical timestamps.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` — an integer starting at 1 and incrementing by 1 on each successful mutation; used by the optimistic concurrency control protocol described in §2.7.

### 2.5. The Logical Clock

The server maintains a logical UTC clock used by every time-dependent rule (quotation expiry, document expiry, claim windows, year-to-date roll-ups). The clock is set exclusively via the platform-admin test-driving capability, which accepts a `to_iso8601` payload field naming the new logical instant; a missing or unparseable `to_iso8601` is rejected with `ERR_VALIDATION` (HTTP 400), and the endpoint responds 200 with `data` of the form `{"current_utc": "<the to_iso8601 string as supplied>"}`. The clock may be set to any parseable instant — forward or backward; the sweeps only ever transition entities forward into `EXPIRED`. Its startup default before any such call is exactly `2026-08-01T00:00:00Z`. The server never falls back to wall-clock time. Advancing the clock triggers two sweeps: every `VERIFIED` `ComplianceDocument` whose `expires_at` is strictly earlier than the new clock value transitions to `EXPIRED` (with the compliance-posture cascade described in §2.9); and every non-terminal `Quotation` whose `valid_until` is strictly earlier than the new clock value transitions to `EXPIRED`.

### 2.6. Money, Precision, and Rounding

All monetary amounts are integer cents (`*_cents` fields). Intermediate calculations that produce a fractional value round **half-up** at the step where rounding is specified. Where a calculation rule labels a step "2 decimal places" or "0 decimal places", that step rounds half-up to that many decimals. Year-to-date roll-ups (`Buyer.ytd_gmv_cents`, `Agent.commission_ytd_cents`) are scoped to the calendar year of the current logical clock, not wall-clock time. `Agent.commission_ytd_cents` specifically is the sum of `final_commission_cents` over the agent's `CLOSED` purchase orders whose `created_at` falls in the clock's calendar year (the year in which the PO closed is irrelevant); `Buyer.ytd_gmv_cents` follows the tier-basis rule of §3.7.

### 2.7. Optimistic Concurrency Control

Two write endpoints require the caller to echo back the version it last observed on the parent entity:

- Counter-offering a `Quotation` requires the request body to carry `expected_quotation_version` equal to the quotation's current `version`.
- Amending a `PurchaseOrder` requires the request body to carry `expected_po_version` equal to the PO's current `version`.

If the supplied expected version no longer matches the entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). A missing or non-integer expected-version field is instead rejected with `ERR_VALIDATION` (HTTP 400). No other endpoint takes a version field; reads never advance the version.

### 2.8. Capacity Bookkeeping by Delivery Month

Each factory declares a `monthly_capacity_units` ceiling — the maximum committed units per calendar delivery month across all of its live purchase orders. The committed load for a given factory and month is the sum of `open_qty` plus `shipped_qty` over that factory's purchase orders whose `delivery_month` matches the target month and whose `status` is one of `ACTIVE`, `PARTIALLY_SHIPPED`, or `SHIPPED`. When a quotation is accepted or a PO is amended in a way that would change the quantity or month, the check is `committed_units + candidate_qty <= monthly_capacity_units`; equality is allowed, anything larger is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422). On acceptance the candidate quantity is the accepted `ordered_qty`; on amendment the PO being amended is excluded from the committed-load sum and the candidate quantity is the amended `ordered_qty` minus the PO's `cancelled_qty`. A `CANCELLED` PO contributes zero to committed load.

### 2.9. Factory Compliance Posture and the Ship Gate

Each factory carries a `compliance_posture` of `COMPLIANT` or `NON_COMPLIANT`, derived from the compliance documentation covering the product categories of that factory's live purchase orders. Live for this purpose means a `PurchaseOrder` whose `status` is `ACTIVE`, `PARTIALLY_SHIPPED`, or `SHIPPED`. The product categories in play are collected from the `SourcingRequest`s linked via those POs. If the factory has no such live POs, the posture is trivially `COMPLIANT`. Otherwise the required document types are the union of:

- `APPAREL` requires `SOCIAL_AUDIT` and `PRODUCT_TEST`.
- `ELECTRONICS` requires `PRODUCT_TEST` and `LAB_TEST`.
- `TOYS` requires `PRODUCT_TEST`, `LAB_TEST`, and `SOCIAL_AUDIT`.
- `FURNITURE` requires `FIRE_SAFETY` and `PRODUCT_TEST`.

The posture is `COMPLIANT` if and only if for every required doc type there exists a `ComplianceDocument` on the factory with that `doc_type`, `status` `VERIFIED`, and `expires_at` strictly later than the current logical clock; otherwise the posture is `NON_COMPLIANT`. Every time the posture flips, the platform rewrites `ship_blocked` on every one of the factory's live POs: `ship_blocked` becomes true when the posture flips to `NON_COMPLIANT`, false when it flips back to `COMPLIANT`. Posture is recomputed whenever a compliance document is verified, whenever the clock sweep expires a document, and whenever a new live PO is created against the factory.

### 2.10. Audit Grading and the Factory Gate

A factory's audit program is split into two variants keyed on `audit_type`. The score is always computed from four category inputs — `quality_system_score`, `social_compliance_score`, `production_capability_score`, `financial_stability_score`, each an integer in 0..100 — plus an optional `critical_findings` count that defaults to 0. Each category contributes `round_half_up(score_i * weight_i, 2 decimal places)`; the four contributions are summed. The weights differ by variant: `SCREENING` uses 0.35 for quality system, 0.25 for social compliance, 0.25 for production capability, and 0.15 for financial stability; `ONSITE` uses 0.40, 0.30, 0.20, and 0.10 respectively. For the `ONSITE` variant only, each critical finding deducts 5 points from the raw sum, with the sum floored at zero. The final `score` is the result rounded half-up to 0 decimal places (an integer). The `grade` is then banded: score at least 85 is `A`, at least 70 is `B`, at least 50 is `C`, below 50 is `D`.

Score and grade are computed at creation time and are immutable thereafter. Only after the audit has been approved does it affect the factory: approval of an `ONSITE` audit sets `factory.latest_audit_grade` to this audit's grade and `factory.audit_score` to this audit's score, with ties among multiple approved onsite audits resolved by `approved_at` (most recent first), tie-broken by `created_at` ascending, and — if audits are still tied on both timestamps — by creation order, earliest-created first; the factory's `version` increments by 1 whenever these fields are rewritten. Approving a `SCREENING` audit sets `approved_at` but does not touch the factory's grade or score fields. A factory with no approved onsite audit reports `latest_audit_grade` `NONE` and `audit_score` 0.

### 2.11. Nested Resource Retrieval and Left-to-Right Validation

URL paths nest child resources beneath their parents (for example, audits beneath factories, samples and quotations beneath sourcing requests, milestones, inspections, shipments and claims beneath purchase orders). The server validates path identifiers left-to-right, parent before child. A nonexistent parent yields the parent's not-found error (`ERR_FACTORY_NOT_FOUND`, `ERR_SOURCING_REQUEST_NOT_FOUND`, `ERR_PURCHASE_ORDER_NOT_FOUND`); a nonexistent child beneath an existing parent yields the child's not-found error (`ERR_AUDIT_NOT_FOUND`, `ERR_COMPLIANCE_DOCUMENT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_QUOTATION_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_QUALITY_CLAIM_NOT_FOUND`). Top-level lookups use the corresponding not-found error (`ERR_BUYER_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`).

### 2.12. Validation Priority Order

When several validation rules could fire on the same request, the server evaluates them in this strict order and reports the first failure:

1. **Auth presence** — `X-User-ID` and `X-User-Role` present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role admission** — the role is in the endpoint's permitted list (`ERR_FORBIDDEN_ROLE`).
3. **Path existence** — every path identifier resolves, parent before child (`ERR_{RESOURCE}_NOT_FOUND`).
4. **Ownership scoping** — entity-backed caller owns the target (`ERR_OWNERSHIP_SCOPE_VIOLATION`).
5. **State precondition** — the target entity is in the state the transition requires (e.g. `ERR_SAMPLE_NOT_REVIEWABLE`, `ERR_QUOTATION_NOT_OPEN`, `ERR_PO_NOT_ACTIVE`, `ERR_CLAIM_NOT_REVIEWABLE`, `ERR_AUDIT_NOT_REVIEWABLE`, `ERR_DOC_NOT_VERIFIABLE`, `ERR_SR_NOT_CANCELLABLE`, `ERR_SR_NOT_ACTIVE`, `ERR_SAMPLE_NOT_RESUBMITTABLE`, `ERR_MILESTONE_NOT_SUBMITTABLE`, `ERR_MILESTONE_NOT_VERIFIABLE`, `ERR_INSPECTION_NOT_RECORDABLE`, `ERR_INSPECTION_NOT_CANCELLABLE`, `ERR_SHIPMENT_STATE_INVALID`).
6. **Optimistic concurrency** — `expected_quotation_version` / `expected_po_version` matches current `version` (`ERR_STALE_VERSION`).
7. **Compliance and factory-status gates** — shipment booking and inspection booking require `ship_blocked` false (`ERR_FACTORY_NOT_COMPLIANT`); quotation create/accept, shipment booking, and inspection booking require the factory `ACTIVE` (`ERR_FACTORY_SUSPENDED`).
8. **Audit grade, segregation of duties, and inspection-type readiness** — quotation creation and acceptance require `latest_audit_grade` in {`A`, `B`} (`ERR_FACTORY_GRADE_INSUFFICIENT`); claim adjudication requires the approver differ from `po.assigned_agent_id` (`ERR_SEGREGATION_OF_DUTIES`); DUPRO booking requires `production_status` `IN_PRODUCTION` (`ERR_PO_NOT_READY_FOR_DUPRO`); PSI booking requires `production_status` `PRODUCTION_COMPLETE` (`ERR_PO_NOT_READY_FOR_PSI`).
9. **Structural constraints** — at most one non-terminal quotation per (`sourcing_request`, `factory`) (`ERR_DUPLICATE_QUOTATION`); milestone plan must be locked before submit (`ERR_MILESTONE_PLAN_INCOMPLETE`); milestone creation rejected after lock (`ERR_MILESTONE_PLAN_LOCKED`); weight pushing the cumulative total over 100 (`ERR_INVALID_WEIGHT_TOTAL`); inspector half-open window overlap (`ERR_INSPECTION_WINDOW_CONFLICT`); defect counts exceeding `sample_size` (`ERR_AQL_SAMPLE_MISMATCH`).
10. **Temporal windows** — quotation counter/accept requires the logical clock at or before `valid_until` (`ERR_QUOTATION_EXPIRED`); quality-claim filing requires the logical clock at or before the PO's latest `delivered_at` plus 30 days (`ERR_CLAIM_WINDOW_CLOSED`).
11. **Fiscal / capacity / quantity bounds** — capacity ceiling (`ERR_CAPACITY_EXCEEDED`), minimum order quantity (`ERR_QTY_BELOW_MOQ`), amend below shipped-plus-cancelled (`ERR_AMEND_BELOW_SHIPPED`), ship quantity out of range (`ERR_SHIP_QTY_INVALID`), chargeback exceeding remaining payable (`ERR_CLAIM_EXCEEDS_PAYABLE`).

A later-priority failure is masked by any earlier-priority failure on the same request. Request-body schema validation (missing or mistyped required fields, `ERR_VALIDATION`, HTTP 400) is not part of the numbered business-rule order: each endpoint validates its required body fields after role admission and path-existence resolution and before the remaining buckets, with two exceptions — the optimistic-concurrency field (`expected_quotation_version`, `expected_po_version`) is validated at the optimistic-concurrency step (bucket 6), and PO amendment validates its whole change-set (the `expected_po_version` field, the at-least-one-changed-field requirement, and field types) only after the state precondition. Required string fields are checked only for presence and string type — empty strings are accepted — unless a rule states otherwise. Where §3 enumerates an endpoint-specific order, that enumeration governs: in particular, quotation countering evaluates state precondition → optimistic concurrency → counter-party (`ERR_WRONG_COUNTER_PARTY`) → ownership → round cap (`ERR_NEGOTIATION_ROUND_EXCEEDED`) → expiry, and quotation acceptance evaluates its state precondition before ownership (§3.4).

### 2.13. Status Code Conventions

New resource creation returns HTTP 201. Modifications of an existing resource — including all state transitions, accept/counter/reject calls, verifications, reviews, and sweeps — return HTTP 200.

## 3. Business Logic & Workflows

### 3.1. Platform Bootstrap and Registry

A `PlatformAdmin` bootstraps the actors before any commercial work begins. Creating a `Buyer` records the buyer company `name` and its `country_code` (conventionally an ISO 3166-1 alpha-2 code; carried as an opaque string with no format validation); the new buyer starts with `credit_balance_cents` 0, `ytd_gmv_cents` 0, and `status` `ACTIVE`. Buyer status is always `ACTIVE` in v1 — no close transition is exposed. Creating an `Agent` records the agent's `name` and the `agency_name` the agent works for; the new agent starts with `commission_ytd_cents` 0. Creating an `Inspector` records the inspector's `name` and operating `region`.

A `SourcingAgent` registers candidate factories by supplying the factory's legal `name`, `country_code`, and `monthly_capacity_units` (an integer of at least 1 — the maximum committed units the factory will accept per calendar delivery month across all POs). The factory starts `ACTIVE` with `compliance_posture` `COMPLIANT`, `debit_balance_cents` 0, and `latest_audit_grade` `NONE` (with `audit_score` 0).

### 3.2. Factory Auditing and Compliance Documentation

Once a factory is registered, the same or another `SourcingAgent` conducts audits. Audits may be created for a factory in any status (including `SUSPENDED`), and any number of audits may be `SUBMITTED` concurrently. The agent submits an audit with `audit_type` (`SCREENING` or `ONSITE`), the four category scores (each 0..100), and an optional `critical_findings` count (a non-negative integer defaulting to 0; anything else yields `ERR_VALIDATION`). The platform stamps `conducted_by_agent_id` from the caller's `X-User-ID`, computes `score` and `grade` per the audit-score rule in §2.10, and lands the audit in `SUBMITTED`. A `ComplianceOfficer` then reviews it: approving flips the status to `APPROVED` and stamps `approved_at` with the current logical clock; rejecting flips it to `REJECTED`. An audit in any state other than `SUBMITTED` is not reviewable — both approve and reject fail with `ERR_AUDIT_NOT_REVIEWABLE`. When an `ONSITE` audit is approved, the factory's `latest_audit_grade` and `audit_score` fields are rewritten to reflect the most recently approved onsite audit (with `Factory.version` incremented by 1); `SCREENING` approvals leave those fields untouched.

In parallel, the agent uploads compliance documents: `doc_type` one of `SOCIAL_AUDIT`, `PRODUCT_TEST`, `LAB_TEST`, or `FIRE_SAFETY`, an `issued_date` (ISO 8601 date, carried as an opaque string with no format validation), and an `expires_at` instant (which must parse as an ISO 8601 datetime, else `ERR_VALIDATION`; it is not required to lie in the future). Upload is allowed for a factory in any status and does not itself trigger a posture recompute — §2.9 lists the recompute triggers. New documents land `SUBMITTED`. A `ComplianceOfficer` verifies (`SUBMITTED` → `VERIFIED`) or rejects (`SUBMITTED` → `REJECTED`); anything not `SUBMITTED` is rejected with `ERR_DOC_NOT_VERIFIABLE`. Verification recomputes the factory's `compliance_posture`; if the posture flips to `COMPLIANT`, every live PO of the factory has `ship_blocked` cleared. Advancing the logical clock past a document's `expires_at` sweeps it from `VERIFIED` to `EXPIRED`, recomputes posture, and — if the posture flips to `NON_COMPLIANT` — sets `ship_blocked` to true on every live PO of the factory. This document → posture → ship-gate cascade is the intended serialization point between compliance review and shipment booking.

### 3.3. Sourcing Requests and the Sample Cycle

A `BuyerManager` opens a sourcing engagement by creating a `SourcingRequest` with `assigned_agent_id` (the agent owning the engagement; carried as an opaque string and not resolved against the agent registry), a `title` describing the product brief, a `product_category` (one of `APPAREL`, `ELECTRONICS`, `TOYS`, `FURNITURE`), a `target_price_cents` unit price (any integer; no range validation), a `quantity` of at least 1, and a `commission_mode` (`FOB` or `CIF`) that will later select the commission base. The request is stamped with `buyer_id` from the caller's `X-User-ID` and starts `OPEN`. The first `Sample` or `Quotation` created under the request flips it from `OPEN` to `IN_PROGRESS`; this transition is system-driven and needs no explicit call.

The agent submits samples with free-text `notes` against a request that is `OPEN` or `IN_PROGRESS` (`ERR_SR_NOT_ACTIVE` otherwise); a fresh sample has `revision_count` 0 and status `SUBMITTED`. The buyer then reviews each submitted sample with a `decision` of `APPROVE` or `REQUEST_REVISION` (an optional `comments` field may accompany the review; it is accepted but not persisted anywhere). Review requires the sample to be `SUBMITTED` (`ERR_SAMPLE_NOT_REVIEWABLE` otherwise), the caller to own the parent sourcing request, and the request itself to be `OPEN` or `IN_PROGRESS` (`ERR_SR_NOT_ACTIVE` otherwise). Approval moves the sample to `APPROVED`. Requesting a revision moves the sample to `REVISION_REQUESTED` — unless the sample's `revision_count` has already reached the revision cap of 3, in which case the review call still succeeds with HTTP 200 but the sample body shows status `REJECTED`; the 4th revision request is refused and the sample is terminally rejected. The agent resubmits a `REVISION_REQUESTED` sample with fresh `notes`, which increments `revision_count` by 1 and returns the sample to `SUBMITTED`; resubmission requires the sample to be `REVISION_REQUESTED` (`ERR_SAMPLE_NOT_RESUBMITTABLE` otherwise) and the caller to be the request's `assigned_agent_id`, and it does not gate on the sourcing request's own status.

The buyer may cancel a request while it is `OPEN` or `IN_PROGRESS` — anything else is rejected with `ERR_SR_NOT_CANCELLABLE`. Cancelling cascades: every non-terminal `Sample` (statuses `SUBMITTED`, `REVISION_REQUESTED`) flips to `REJECTED`, and every non-terminal `Quotation` (statuses `OPEN`, `COUNTERED`) flips to `REJECTED`.

### 3.4. Quotation Negotiation

A `FactoryRep` opens price negotiation by submitting an initial quotation against a sourcing request, carrying `unit_price_cents`, `moq` (minimum order quantity), `lead_time_days`, and `valid_until` (the offer's expiry instant). The three numeric fields accept any integer with no range validation; `valid_until` must parse as an ISO 8601 datetime (`ERR_VALIDATION` otherwise) but is not checked against the logical clock at creation. The platform stamps `factory_id` from the caller's `X-User-ID`, initializes `round_count` to 0 and `last_actor_role` to `FACTORY`, and lands the quotation in `OPEN`. Creation first requires the sourcing request to be `OPEN` or `IN_PROGRESS` (`ERR_SR_NOT_ACTIVE` otherwise) and the caller's `X-User-ID` to resolve to a registered `Factory` (`ERR_FACTORY_NOT_FOUND` otherwise). Two business gates then guard the creation: the factory must be `ACTIVE` (a `SUSPENDED` factory yields `ERR_FACTORY_SUSPENDED`), and `latest_audit_grade` must be `A` or `B` (otherwise `ERR_FACTORY_GRADE_INSUFFICIENT`). A third, structural gate enforces that at most one non-terminal quotation exists per (`sourcing_request`, `factory`) pair — attempting a second while one is still live yields `ERR_DUPLICATE_QUOTATION`. Creation also drives the parent request from `OPEN` to `IN_PROGRESS` if this is the request's first child activity.

Counter-offers alternate strictly between the two sides. The state `OPEN` means the factory set the current terms; `COUNTERED` means the buyer set them. When the current terms came from `FACTORY`, only a `BuyerManager` may counter; when they came from `BUYER`, only a `FactoryRep` may counter — a violation is rejected with `ERR_WRONG_COUNTER_PARTY`. The countering request carries a new `unit_price_cents`, optionally a new `valid_until`, and `expected_quotation_version` matching the quotation's current `version`. Preconditions are evaluated in this order: the quotation must be `OPEN` or `COUNTERED` (`ERR_QUOTATION_NOT_OPEN`); the expected version must match (else `ERR_STALE_VERSION`); the caller must be the correct side and own the engagement (else `ERR_WRONG_COUNTER_PARTY`, then `ERR_OWNERSHIP_SCOPE_VIOLATION`); `round_count` must still be below the negotiation round cap of 6 (else `ERR_NEGOTIATION_ROUND_EXCEEDED`); and the logical clock must be at or before the quotation's current, pre-update `valid_until` (else `ERR_QUOTATION_EXPIRED`). A successful counter increments `round_count` by 1, flips `last_actor_role` to the countering side, replaces `unit_price_cents` (and `valid_until` if supplied) with the payload values, alternates the status between `OPEN` and `COUNTERED`, and increments `Quotation.version` by 1.

The buyer accepts a quotation by supplying `ordered_qty`, `delivery_month` (a `YYYY-MM` string with month 01–12 that keys the factory's capacity bucket), `expected_quotation_version`, and `freight_cents` and `insurance_cents` (optional integers, both defaulting to 0; accepted and stored on the PO for either `commission_mode`, though only `CIF` mode feeds them into the commission base). Acceptance enforces, in order: the quotation must be `OPEN` or `COUNTERED` (`ERR_QUOTATION_NOT_OPEN`); the caller must own the sourcing request; the expected version must match; the logical clock must be at or before `valid_until` (`ERR_QUOTATION_EXPIRED`); the factory must be `ACTIVE` (`ERR_FACTORY_SUSPENDED`); `latest_audit_grade` must be `A` or `B` (`ERR_FACTORY_GRADE_INSUFFICIENT`); `ordered_qty` must be at least the quotation's `moq` (`ERR_QTY_BELOW_MOQ`); and the capacity rule of §2.8 must admit `ordered_qty` into `delivery_month` (`ERR_CAPACITY_EXCEEDED`). On success the platform creates the `PurchaseOrder` (status `ACTIVE`, `production_status` `PLACED`, `ordered_qty` and `unit_price_cents` taken from the accept payload / quotation terms), computes the provisional commission (§3.7), links the quotation to the new PO via `purchase_order_id`, transitions the quotation to `ACCEPTED`, advances the sourcing request to `PO_PLACED`, recomputes `Buyer.ytd_gmv_cents` (which now includes this PO's `total_cents`), increments `Quotation.version` by 1, and recomputes the factory's `compliance_posture` to account for the new live PO. The accept response carries the newly created `PurchaseOrder` in `data` with HTTP 200 (not the quotation, and not 201).

The buyer may also reject a quotation outright while it is `OPEN` or `COUNTERED`; rejection moves it to `REJECTED`. Independently, the clock sweep moves any non-terminal quotation whose `valid_until` is strictly earlier than the new clock value to `EXPIRED`.

### 3.5. Purchase Order Lifecycle and Amendment

The newly created `PurchaseOrder` carries `quotation_id`, `sourcing_request_id`, `buyer_id`, `factory_id`, and `assigned_agent_id` copied from their parents, plus `ordered_qty`, `unit_price_cents`, `delivery_month`, `freight_cents`, and `insurance_cents` from the accept payload. `total_cents` is exactly `ordered_qty * unit_price_cents`. `shipped_qty` and `cancelled_qty` start at 0; `open_qty` is always `ordered_qty - shipped_qty - cancelled_qty` — the invariant `ordered == shipped + cancelled + open` holds throughout the lifecycle. `milestone_plan_locked` starts false, `progress_pct` starts 0, `production_status` starts `PLACED`, `latest_psi_result` starts `NONE`, `document_status` starts `PENDING`, and `ship_blocked` reflects the factory's current posture. `remaining_payable_cents` is `total_cents` minus the sum of `total_chargeback_cents` over the PO's `APPROVED` quality claims. The main `status` dimension walks `ACTIVE` → `PARTIALLY_SHIPPED` → `SHIPPED` → `CLOSED` (or `CANCELLED` from `ACTIVE`/`PARTIALLY_SHIPPED`).

The assigned `SourcingAgent` may amend a live PO — one whose `status` is `ACTIVE` or `PARTIALLY_SHIPPED`; anything else yields `ERR_PO_NOT_ACTIVE`. The amend call carries `expected_po_version` plus at least one of `unit_price_cents`, `ordered_qty`, or `delivery_month`; an amend with no changed field is rejected with `ERR_VALIDATION`. Supplied values are validated only for type (integer price and quantity; a `YYYY-MM` string with month 01–12 for the month) — no other range constraint applies beyond the below-shipped floor. The ordered quantity may not be amended below `shipped_qty + cancelled_qty` — equality is allowed, anything lower yields `ERR_AMEND_BELOW_SHIPPED`. A quantity or month change re-runs the §2.8 capacity check (`ERR_CAPACITY_EXCEEDED` on breach; §2.8 describes the amendment variant, which excludes the PO itself and nets out `cancelled_qty`). A successful amend recomputes `total_cents`, `open_qty`, `provisional_commission_cents`, `commission_rate_bp`, and `remaining_payable_cents`, and increments `PurchaseOrder.version` by 1.

Cancelling a PO is likewise the assigned agent's call, allowed only while `status` is `ACTIVE` or `PARTIALLY_SHIPPED`. Cancellation moves the PO to `CANCELLED`, adds `open_qty` into `cancelled_qty`, sets `open_qty` to 0, and releases the capacity commitment — the factory's `delivery_month` bucket is reduced by the former open quantity, since `CANCELLED` POs contribute zero to committed load. Non-`VERIFIED` milestones remain on the books but freeze; `VERIFIED` milestones keep `progress_pct` frozen at its current value.

### 3.6. Production Milestones and Inspections

While a PO is `ACTIVE`, the assigned agent builds the milestone plan by adding milestones with a `name` (e.g., `CUTTING`, `SEWING`, `PACKING`) and a `weight_pct` between 1 and 100. Milestone creation is allowed only while `milestone_plan_locked` is false. After each creation, if the cumulative weight across all of the PO's milestones equals exactly 100, `milestone_plan_locked` flips to true — the plan is locked. A creation that would push the cumulative weight above 100 is rejected with `ERR_INVALID_WEIGHT_TOTAL`; one attempted after the plan is locked is rejected with `ERR_MILESTONE_PLAN_LOCKED`. New milestones land in `PLANNED`, and `production_status` stays `PLACED` until the first factory submit.

The `FactoryRep` submits evidence for a milestone by posting an `evidence_note`. Submission requires the milestone to be `PLANNED` or `REJECTED` (`ERR_MILESTONE_NOT_SUBMITTABLE` otherwise), the caller to belong to the PO's `factory_id`, the plan to be locked (`ERR_MILESTONE_PLAN_INCOMPLETE` otherwise), and the PO to be `ACTIVE` (`ERR_PO_NOT_ACTIVE` otherwise). The first submission on the PO advances `production_status` from `PLACED` to `IN_PRODUCTION`. The assigned agent then verifies or rejects each `SUBMITTED` milestone (anything else yields `ERR_MILESTONE_NOT_VERIFIABLE` on both calls); verification additionally requires the PO to be `ACTIVE` (`ERR_PO_NOT_ACTIVE` otherwise), while rejection imposes no PO-state gate. Verification adds the milestone's `weight_pct` into `po.progress_pct`; rejection does not change progress. When all of the PO's milestones reach `VERIFIED`, `production_status` advances to `PRODUCTION_COMPLETE`.

The assigned agent also books inspections, supplying an `inspector_id` (a non-empty string; it is not resolved against the inspector registry at booking time), an `inspection_type` of `DUPRO` or `PSI`, a `scheduled_date` (ISO 8601 calendar date of the window start; any valid date is accepted, past or future), a `duration_days` between 1 and 5, and a `lot_size` of at least 1 unit. The inspection window is half-open — it covers `scheduled_date` up to but not including `scheduled_date + duration_days`. Booking enforces, in §2.12 order: the PO must be `ACTIVE`; the factory must be `ACTIVE` and the PO's `ship_blocked` false; a `DUPRO` booking requires `production_status` `IN_PRODUCTION` (`ERR_PO_NOT_READY_FOR_DUPRO`); a `PSI` booking requires `production_status` `PRODUCTION_COMPLETE` (`ERR_PO_NOT_READY_FOR_PSI`); and the inspector must not already have a `BOOKED` inspection — only `BOOKED` inspections participate in this check — whose half-open window overlaps the requested one (`ERR_INSPECTION_WINDOW_CONFLICT`). At booking time the platform derives `sample_size` from `lot_size` per the AQL table in §3.8 and lands the inspection in `BOOKED`, with the three defect counts null and `result` `NONE`.

The assigned `Inspector` records the result by submitting `defects_critical`, `defects_major`, and `defects_minor`; each count must be a non-negative integer (`ERR_VALIDATION` otherwise). The sum of the three defect counts may not exceed `sample_size` (`ERR_AQL_SAMPLE_MISMATCH`, HTTP 422). The inspection must be `BOOKED` (`ERR_INSPECTION_NOT_RECORDABLE` otherwise) and the caller must be the inspection's `inspector_id`. Recording computes the `result` per §3.8 (`PASSED` or `FAILED`) and flips the status to `RESULT_RECORDED`. When the inspection is a `PSI`, the PO's `latest_psi_result` is rewritten to this result; the field always reflects the most recently recorded PSI — the last record-result call on a PSI of that PO wins. The assigned agent may cancel a `BOOKED` inspection; anything else yields `ERR_INSPECTION_NOT_CANCELLABLE`.

### 3.7. Commission Calculation — Provisional and Final Variants

The agent's commission on a PO is computed twice: once provisionally at PO creation, once finally at PO close. The two variants share the tiered structure but evaluate their tier basis at different times, so the final figure may differ from the provisional even for identical PO data.

**Step 1 — tier selection.** The tier basis is the buyer's `ytd_gmv_cents` — the sum of `total_cents` over the buyer's purchase orders whose status is `ACTIVE`, `PARTIALLY_SHIPPED`, `SHIPPED`, or `CLOSED` and whose `created_at` falls in the calendar year of the current logical clock. For the provisional variant the basis is evaluated **after** the new PO's `total_cents` is included. For the final variant the basis is re-evaluated at close time, reflecting every PO accepted since. The tier boundaries are inclusive on the lower edge:

- basis below 10,000,000 cents → rate 500 basis points (5%).
- basis at least 10,000,000 and below 50,000,000 cents → rate 400 basis points (4%). A basis of exactly 10,000,000 therefore yields 4%, not 5%.
- basis at least 50,000,000 cents → rate 300 basis points (3%).

**Step 2 — base selection.** The base is keyed on the sourcing request's `commission_mode`. For `FOB`, the base is `po.total_cents`. For `CIF`, the base is `po.total_cents + po.freight_cents + po.insurance_cents`.

**Step 3 — commission.** The commission is `base * rate_bp / 10000`, rounded half-up to 0 decimal places (integer cents). For `CIF` only, the result is then capped at `po.total_cents` multiplied by 0.12, with that cap rounded half-up to integer cents; the commission is the smaller of the two. The applied tier rate is stored in `commission_rate_bp` (one of 500, 400, 300). The provisional variant's result is stored in `provisional_commission_cents`; the final variant's result is stored in `final_commission_cents`, which remains null until the PO closes.

### 3.8. AQL Sampling and Result Calculation

Inspections use an AQL 2.5 major-defect sampling plan. The sample size `n` is derived from `lot_size` at booking time with inclusive boundaries:

- `lot_size` at most 500 → `n` = 50.
- `lot_size` between 501 and 1200 inclusive → `n` = 80. Exactly 501 therefore yields 80, not 50.
- `lot_size` between 1201 and 3200 inclusive → `n` = 125.
- `lot_size` at least 3201 → `n` = 200.

Each sample size carries an acceptance number `Ac` and rejection number `Re` for major defects:

- `n` = 50 → `Ac` 3, `Re` 4.
- `n` = 80 → `Ac` 5, `Re` 6.
- `n` = 125 → `Ac` 7, `Re` 8.
- `n` = 200 → `Ac` 10, `Re` 11.

The result is then determined by three checks applied in order: the inspection is `FAILED` if `defects_critical` is greater than 0; otherwise it is `FAILED` if `defects_major` is at least `Re`; otherwise it is `FAILED` if `defects_minor` is greater than twice `Ac`; otherwise it is `PASSED`. The boundary case `defects_major` exactly equal to `Ac` passes.

### 3.9. Shipment Booking, Document Handoff, and PO Close

Once production is complete and inspections support it, the assigned agent books shipments against the PO, supplying `shipped_qty` and a `vessel_ref` (the booking/vessel reference). `shipped_qty` must be at least 1 and at most the PO's current `open_qty` (`ERR_SHIP_QTY_INVALID`, HTTP 422). Booking first requires the PO to be `ACTIVE` or `PARTIALLY_SHIPPED` (`ERR_PO_NOT_ACTIVE` otherwise), then enforces the readiness gates in §2.12 order: the factory must be `ACTIVE` (`ERR_FACTORY_SUSPENDED`); the PO's `ship_blocked` must be false (`ERR_FACTORY_NOT_COMPLIANT`); `production_status` must be `PRODUCTION_COMPLETE` (`ERR_PO_NOT_READY_FOR_PSI`); and `latest_psi_result` must be `PASSED` (`ERR_NO_PASSING_PSI`). On success the platform adds `shipped_qty` into `po.shipped_qty` and recomputes `open_qty`. If this is the first shipment and the booked quantity is less than `open_qty`, the PO advances from `ACTIVE` to `PARTIALLY_SHIPPED`; a booking that drives `open_qty` to zero advances the PO to `SHIPPED` directly (or from `PARTIALLY_SHIPPED` to `SHIPPED`). The new shipment lands in `BOOKED`.

The factory then hands over shipping documents by supplying `doc_refs`, a non-empty array of document-reference strings (bill of lading, packing list, certificate of origin, and the like); an empty array — or any element that is not a string — is rejected with `ERR_VALIDATION`. The shipment must be `BOOKED` (`ERR_SHIPMENT_STATE_INVALID` otherwise) and the caller must belong to the PO's factory. Handover advances the shipment from `BOOKED` to `DOCS_HANDED_OVER` and flips `po.document_status` from `PENDING` to `HANDED_OVER` on the first such handover.

The buyer confirms receipt of a handed-over shipment; the shipment must be `DOCS_HANDED_OVER` (`ERR_SHIPMENT_STATE_INVALID` otherwise) and the caller must own the PO's `buyer_id`. Confirmation stamps `delivered_at` with the current logical clock and advances the shipment to `DELIVERED`. If, after this delivery, the PO's `open_qty` is zero and every non-`CANCELLED` shipment of the PO is `DELIVERED`, the PO transitions from `SHIPPED` to `CLOSED`. Closing computes the final commission per §3.7 (with the tier re-evaluated from the buyer's `ytd_gmv_cents` at close time), stores the result in `final_commission_cents` and re-stores `commission_rate_bp` from the final variant, and advances the sourcing request from `PO_PLACED` to `COMPLETED`. The closed PO's `final_commission_cents` thereafter feeds `Agent.commission_ytd_cents` per the roll-up rule of §2.6.

The assigned agent may cancel a `BOOKED` shipment; anything else yields `ERR_SHIPMENT_STATE_INVALID`. Cancellation subtracts the shipment's `shipped_qty` from `po.shipped_qty` and recomputes `open_qty`; the PO's status is then recomputed — `ACTIVE` if no live (non-`CANCELLED`) shipments remain, otherwise `PARTIALLY_SHIPPED` if `open_qty` is above zero, otherwise `SHIPPED`. In particular, if the PO had been `PARTIALLY_SHIPPED` and this cancellation removes its last live shipment, the PO reverts from `PARTIALLY_SHIPPED` back to `ACTIVE`.

### 3.10. Quality Claims and the Chargeback Cascade

After delivery, the buyer may file a quality claim against the PO. Filing is allowed only while the logical clock is at or before the PO's latest `delivered_at` plus 30 days; if no delivery has happened yet, or the window has closed, filing is rejected with `ERR_CLAIM_WINDOW_CLOSED`. The filing body carries a non-empty `items` array of claim lines, each with a string `description`, `qty_defective` (an integer of at least 1), and `unit_price_cents` (an integer of at least 1); anything else yields `ERR_VALIDATION`. The platform stamps `filed_by_buyer_id` from the caller's `X-User-ID`, computes `base_amount_cents` as the sum over items of `qty_defective * unit_price_cents` (exact integer cents), `defective_qty` as the sum of `qty_defective`, and `defect_rate` as `defective_qty / po.ordered_qty` rounded half-up to 4 decimal places (exposed on the claim as a JSON number), and lands the claim in `FILED`. At filing, `penalty_cents` and `total_chargeback_cents` remain 0.

Adjudication is reserved for a `SourcingAgent` other than the PO's assigned agent — if the caller's agent id equals `po.assigned_agent_id`, the call is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The claim must also be `FILED` (`ERR_CLAIM_NOT_REVIEWABLE` otherwise). Rejection moves the claim to `REJECTED` with no further effect. Approval computes the chargeback per the waterfall below, guards it against the PO's payable balance, and then applies it.

The chargeback calculation proceeds in labeled steps. First, each line's base is `qty_defective * unit_price_cents` (exact integer); `base_amount_cents` is the sum across lines. Second, `defect_rate` is `defective_qty / po.ordered_qty` rounded half-up to 4 decimal places (recomputed at approval against the PO's then-current `ordered_qty`, and re-stored on the claim). Third, a penalty tier is selected on the defect rate with inclusive boundaries: a rate at most 0.05 carries no penalty; a rate above 0.05 and at most 0.10 carries a 2% penalty (a rate of exactly 0.1000 therefore sits in the 2% tier); a rate above 0.10 carries a 5% penalty. Fourth — and the rounding order is pinned — each line's penalty is computed individually as `round_half_up(base_line * penalty_rate, 0 decimal places)`, and `penalty_cents` is the sum of those per-line penalties. Sum-then-round is explicitly not used. Fifth, `total_chargeback_cents` is `base_amount_cents + penalty_cents`. Sixth, the total must not exceed `po.remaining_payable_cents`; a chargeback that would is rejected with `ERR_CLAIM_EXCEEDS_PAYABLE` (HTTP 422).

Approval then cascades. `approved_by_agent_id` is set to the caller's id. The factory's `debit_balance_cents` increases by `total_chargeback_cents`. The buyer's `credit_balance_cents` increases by the same amount — the zero-sum counterpart. The PO's `remaining_payable_cents` decreases by the total. Finally, if the factory's `debit_balance_cents` has reached or exceeded the suspension threshold of 1,000,000 cents, the factory transitions from `ACTIVE` to `SUSPENDED`; every quotation of that factory still in `OPEN` or `COUNTERED` flips to `EXPIRED`; and every PO of that factory with status `ACTIVE` and `shipped_qty` equal to 0 flips to `CANCELLED` (with `cancelled_qty` absorbing `open_qty` and `open_qty` zeroed). This claim → debit → factory-status → quotations/POs cascade is the platform's enforcement mechanism against repeat-offender factories.

## 4. Endpoint Definitions

New resources are returned with HTTP 201. Modifications and state transitions return HTTP 200. List endpoints return HTTP 200 with the paginated envelope of §2.3 and support exact-match filtering through query parameters — audits: `factory_id`, `conducted_by_agent_id`; compliance-documents: `factory_id`, `doc_type`, `status`; sourcing-requests: `buyer_id`, `assigned_agent_id`, `status`; samples: `sourcing_request_id`, `status`; quotations: `sourcing_request_id`, `factory_id`, `purchase_order_id`, `status`; purchase-orders: `buyer_id`, `factory_id`, `quotation_id`, `sourcing_request_id`, `assigned_agent_id`, `status`, `delivery_month`; milestones: `po_id`, `status`; inspections: `po_id`, `inspector_id`, `status`; shipments: `po_id`, `status`; quality-claims: `po_id`, `filed_by_buyer_id`, `approved_by_agent_id`, `status`. Unrecognized query parameters are ignored. All endpoints are mounted under `/sourcing`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/sourcing/buyers` | Create a Buyer | PlatformAdmin |
| GET | `/sourcing/buyers/{buyerId}` | Get a Buyer | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/agents` | Create an Agent | PlatformAdmin |
| GET | `/sourcing/agents/{agentId}` | Get an Agent | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/inspectors` | Create an Inspector | PlatformAdmin |
| GET | `/sourcing/inspectors/{inspectorId}` | Get an Inspector | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/factories` | Register a Factory | SourcingAgent |
| GET | `/sourcing/factories/{factoryId}` | Get a Factory | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/factories/{factoryId}/audits` | Conduct (create) a FactoryAudit; score and grade computed at creation | SourcingAgent |
| GET | `/sourcing/audits` | List FactoryAudits (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/audits/{auditId}` | Get a FactoryAudit | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/audits/{auditId}/approve` | Approve a SUBMITTED audit | ComplianceOfficer |
| POST | `/sourcing/audits/{auditId}/reject` | Reject a SUBMITTED audit | ComplianceOfficer |
| POST | `/sourcing/factories/{factoryId}/compliance-documents` | Upload a compliance document | SourcingAgent |
| GET | `/sourcing/compliance-documents` | List ComplianceDocuments (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/compliance-documents/{docId}` | Get a ComplianceDocument | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/compliance-documents/{docId}/verify` | Verify a SUBMITTED document; recomputes factory posture | ComplianceOfficer |
| POST | `/sourcing/compliance-documents/{docId}/reject` | Reject a SUBMITTED document | ComplianceOfficer |
| POST | `/sourcing/sourcing-requests` | Create a SourcingRequest (buyer = caller) | BuyerManager |
| GET | `/sourcing/sourcing-requests` | List SourcingRequests (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/sourcing-requests/{srId}` | Get a SourcingRequest | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/sourcing-requests/{srId}/cancel` | Cancel an OPEN/IN_PROGRESS SourcingRequest; cascades to samples and quotations | BuyerManager |
| POST | `/sourcing/sourcing-requests/{srId}/samples` | Create a Sample (first revision) under a SourcingRequest | SourcingAgent |
| GET | `/sourcing/samples` | List Samples (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/samples/{sampleId}` | Get a Sample | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/samples/{sampleId}/review` | Buyer reviews a SUBMITTED sample: APPROVE or REQUEST_REVISION (4th revision request auto-rejects) | BuyerManager |
| POST | `/sourcing/samples/{sampleId}/resubmit` | Agent resubmits a REVISION_REQUESTED sample (revision_count += 1) | SourcingAgent |
| POST | `/sourcing/sourcing-requests/{srId}/quotations` | Factory submits an initial quotation | FactoryRep |
| GET | `/sourcing/quotations` | List Quotations (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/quotations/{quotationId}` | Get a Quotation | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/quotations/{quotationId}/counter` | Counter-offer; alternates between buyer and factory; OCC on quotation version | BuyerManager, FactoryRep |
| POST | `/sourcing/quotations/{quotationId}/accept` | Buyer accepts quotation; creates the PurchaseOrder; OCC on quotation version | BuyerManager |
| POST | `/sourcing/quotations/{quotationId}/reject` | Buyer rejects a non-terminal quotation | BuyerManager |
| GET | `/sourcing/purchase-orders` | List PurchaseOrders (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/purchase-orders/{poId}` | Get a PurchaseOrder | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/purchase-orders/{poId}/amend` | Amend unit price / quantity / delivery month of a live PO; OCC on PO version | SourcingAgent |
| POST | `/sourcing/purchase-orders/{poId}/cancel` | Cancel a live PO (assigned agent); open units become cancelled | SourcingAgent |
| POST | `/sourcing/purchase-orders/{poId}/milestones` | Add a milestone to the PO plan (allowed until weights total exactly 100) | SourcingAgent |
| GET | `/sourcing/milestones` | List ProductionMilestones (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/milestones/{milestoneId}` | Get a ProductionMilestone | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/milestones/{milestoneId}/submit` | Factory submits milestone evidence | FactoryRep |
| POST | `/sourcing/milestones/{milestoneId}/verify` | Assigned agent verifies a submitted milestone | SourcingAgent |
| POST | `/sourcing/milestones/{milestoneId}/reject` | Assigned agent rejects a submitted milestone | SourcingAgent |
| POST | `/sourcing/purchase-orders/{poId}/inspections` | Book a DUPRO or PSI inspection with an inspector and window | SourcingAgent |
| GET | `/sourcing/inspections` | List Inspections (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/inspections/{inspectionId}` | Get an Inspection | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/inspections/{inspectionId}/record-result` | Inspector records defect counts; result computed per AQL | Inspector |
| POST | `/sourcing/inspections/{inspectionId}/cancel` | Cancel a BOOKED inspection | SourcingAgent |
| POST | `/sourcing/purchase-orders/{poId}/shipments` | Book a shipment against a production-complete, PSI-passed, compliant PO | SourcingAgent |
| GET | `/sourcing/shipments` | List Shipments (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/shipments/{shipmentId}` | Get a Shipment | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/shipments/{shipmentId}/handover-documents` | Factory hands over shipping documents | FactoryRep |
| POST | `/sourcing/shipments/{shipmentId}/confirm-receipt` | Buyer confirms receipt; delivers shipment; may close the PO (final commission) | BuyerManager |
| POST | `/sourcing/shipments/{shipmentId}/cancel` | Cancel a BOOKED shipment; restores open_qty | SourcingAgent |
| POST | `/sourcing/purchase-orders/{poId}/quality-claims` | Buyer files a quality claim (within 30 days of latest delivery) | BuyerManager |
| GET | `/sourcing/quality-claims` | List QualityClaims (filtered) | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| GET | `/sourcing/quality-claims/{claimId}` | Get a QualityClaim | PlatformAdmin, BuyerManager, SourcingAgent, FactoryRep, Inspector, ComplianceOfficer |
| POST | `/sourcing/quality-claims/{claimId}/approve` | Adjudicating agent (not the PO's agent) approves; chargeback applied zero-sum | SourcingAgent |
| POST | `/sourcing/quality-claims/{claimId}/reject` | Adjudicating agent (not the PO's agent) rejects the claim | SourcingAgent |
| POST | `/sourcing/_clock/set_current_utc` | Set the logical clock; sweeps expired documents and quotations | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_OWNERSHIP_SCOPE_VIOLATION` | 403 |
| `ERR_BUYER_NOT_FOUND` | 404 |
| `ERR_AGENT_NOT_FOUND` | 404 |
| `ERR_FACTORY_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_SOURCING_REQUEST_NOT_FOUND` | 404 |
| `ERR_SAMPLE_NOT_FOUND` | 404 |
| `ERR_QUOTATION_NOT_FOUND` | 404 |
| `ERR_PURCHASE_ORDER_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_QUALITY_CLAIM_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_AUDIT_NOT_REVIEWABLE` | 409 |
| `ERR_DOC_NOT_VERIFIABLE` | 409 |
| `ERR_SR_NOT_ACTIVE` | 409 |
| `ERR_SR_NOT_CANCELLABLE` | 409 |
| `ERR_SAMPLE_NOT_REVIEWABLE` | 409 |
| `ERR_SAMPLE_NOT_RESUBMITTABLE` | 409 |
| `ERR_QUOTATION_NOT_OPEN` | 409 |
| `ERR_WRONG_COUNTER_PARTY` | 409 |
| `ERR_NEGOTIATION_ROUND_EXCEEDED` | 409 |
| `ERR_QUOTATION_EXPIRED` | 409 |
| `ERR_PO_NOT_ACTIVE` | 409 |
| `ERR_MILESTONE_NOT_SUBMITTABLE` | 409 |
| `ERR_MILESTONE_NOT_VERIFIABLE` | 409 |
| `ERR_INSPECTION_NOT_RECORDABLE` | 409 |
| `ERR_INSPECTION_NOT_CANCELLABLE` | 409 |
| `ERR_SHIPMENT_STATE_INVALID` | 409 |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 |
| `ERR_FACTORY_SUSPENDED` | 409 |
| `ERR_FACTORY_NOT_COMPLIANT` | 409 |
| `ERR_FACTORY_GRADE_INSUFFICIENT` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUPLICATE_QUOTATION` | 409 |
| `ERR_MILESTONE_PLAN_INCOMPLETE` | 409 |
| `ERR_MILESTONE_PLAN_LOCKED` | 409 |
| `ERR_INVALID_WEIGHT_TOTAL` | 409 |
| `ERR_INSPECTION_WINDOW_CONFLICT` | 409 |
| `ERR_AQL_SAMPLE_MISMATCH` | 422 |
| `ERR_PO_NOT_READY_FOR_DUPRO` | 409 |
| `ERR_PO_NOT_READY_FOR_PSI` | 409 |
| `ERR_NO_PASSING_PSI` | 409 |
| `ERR_CLAIM_WINDOW_CLOSED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_QTY_BELOW_MOQ` | 422 |
| `ERR_AMEND_BELOW_SHIPPED` | 422 |
| `ERR_SHIP_QTY_INVALID` | 422 |
| `ERR_CLAIM_EXCEEDS_PAYABLE` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INTERNAL` | 500 |
