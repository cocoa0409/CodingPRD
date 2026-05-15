# Customs Brokerage API — Product Requirements Document

## 1. Introduction

Import-export customs brokerage is a coordination problem with money, paperwork, and time pressure pressing against each other. A broker takes on a consignor as a client, signs a commission agreement that fixes scope and fees, prepares declaration paperwork against the destination jurisdiction's customs system, fronts the tariff and tax amounts to keep cargo moving, and ultimately invoices the client for reimbursement. Each step touches a different external party — the customs single window, the inspection-and-quarantine authority, banks for advance funding, and the logistics carrier for the underlying shipment — and each party reports back asynchronously through events the broker cannot directly control.

This document specifies the API that orchestrates the workflow above. The system tracks every client company and commission agreement, supports the document-intake and pre-declaration validation that precedes filing, drives a branching state machine over each declaration as customs returns release, query, inspect, or reject responses, computes tariffs and taxes through a multi-step pipeline, funds advances and collects reimbursements with strict segregation of duties, and emits a tamper-evident audit log so that broker management and external auditors can reconstruct every transition after the fact. The API is mounted under `/customs`.

The intended audience for this document is the engineering team implementing the service. Business workflows are described in §3; the §2 chapter ahead establishes the cross-cutting contract — authentication, response envelope, pagination, precision, concurrency control, and the rules that bind state across multiple entities. Every endpoint is summarised in §4 and every error identifier in §5.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming one of the eight roles defined for this system. If either header is missing or empty, the server returns `ERR_AUTH_MISSING` with HTTP 401. If the headers are present but the role named by `X-User-Role` is not permitted to invoke the endpoint, the server returns `ERR_FORBIDDEN` with HTTP 403.

The eight roles are `BrokerOps`, `DeclarationOfficer`, `DocReviewer`, `FilingOfficer`, `InspectionOfficer`, `SettlementOfficer`, `ClientUser`, and `SystemAdmin`. `BrokerOps` is the senior broker operator and is the only role that may create clients, draft agreements, request signature on an agreement, terminate an agreement, or withdraw a declaration. `DeclarationOfficer` prepares declaration content, attaches documents (shared with `ClientUser`), patches mutable fields, requests documents, and amends rejected declarations. `DocReviewer` re-screens documents and performs the pre-validate transition. `FilingOfficer` files pre-validated declarations and responds to queries. `InspectionOfficer` creates inspection cases and records inspection outcomes. `SettlementOfficer` funds the broker advance on a final settlement. `ClientUser` is the external consignor — they sign their own agreements, upload documents, and confirm samples. `SystemAdmin` operates the clock-advance and external-event endpoints and has read access to every resource and to the audit log.

For seven of the eight roles — `BrokerOps`, `DeclarationOfficer`, `DocReviewer`, `FilingOfficer`, `InspectionOfficer`, `SettlementOfficer`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records each operator identifier in the audit log's `actor_id` field, and segregation-of-duties checks compare two such opaque identifiers as plain strings, but the server does not look these identifiers up in any entity table. The remaining role, `ClientUser`, is **entity-backed**: when `X-User-Role` is `ClientUser`, `X-User-ID` is the `id` of the acting `ClientCompany`, and any ownership check on a resource that ultimately resolves to a `ClientCompany` (through `agreement_id` → `client_id`) compares that `ClientCompany.id` to `X-User-ID`. A `ClientUser` may read only their own `ClientCompany`, list only declarations belonging to their own agreements, and read only settlements belonging to those declarations. Cross-tenant access by a `ClientUser` is rejected with `ERR_FORBIDDEN`.

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

List endpoints support pagination via two query-string parameters, `limit` and `offset`. The default value of `limit` is 10; its minimum is 1 and its maximum is 100. The default value of `offset` is 0; its minimum is 0 and it is unbounded above. Any list endpoint sorts results by `created_at` in ascending order. The response envelope's `meta` object exposes four pagination fields for list endpoints: the `limit` and `offset` that were applied, the `total_count` of records matching the filter (across the entire collection, not the current page), and a boolean `has_more` indicating whether further records exist beyond the current page.

### 2.4. Common Resource Properties

Most resources in the system — `ClientCompany`, `CommissionAgreement`, `Declaration`, `ShipmentDocument`, `Filing`, `InspectionCase`, and `Settlement` — carry four common fields in addition to their domain attributes. The `id` is a server-minted UUID (no entity-type prefix). The `created_at` and `updated_at` timestamps are ISO 8601 UTC strings with three fractional digits; `created_at` is set once at insert time and never mutated thereafter, and `updated_at` is refreshed on every mutation. The `version` field is an integer that starts at 1 on creation and increments by one on every successful mutation, including state transitions performed through dedicated action endpoints.

Two resources are minimal records that omit `updated_at` and `version` entirely: `RejectionRecord` and `AuditLog`. Both carry only `id` and `created_at`. The two further auxiliary records — `ExternalEvent`, used to drive system transitions, and the response envelope's request metadata — also do not expose a `version`. The `RejectionRecord` and `AuditLog` rows are append-only by design; once inserted, they are never edited.

### 2.5. Optimistic Concurrency Control

Every endpoint that mutates a resource — patch endpoints and the action endpoints that drive state transitions — accepts an optional `version` field in the request body. When present, the server compares it against the current `version` of the target resource; if the values differ, the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409 with no state change. When `version` is omitted from the request body, the server skips the comparison and proceeds (a deliberate escape hatch for callers that have already serialized externally). On a successful mutation, the new `version` is the prior value plus one. The audit log records each transition with the actor identifier and the before/after state pair.

### 2.6. Nested Resource Retrieval and 404 Ordering

Several endpoints take more than one identifier in their URL path — for example, an action endpoint on a settlement implicitly resolves through to the declaration and the agreement. When multiple identifiers appear in a path, the server validates them left-to-right and returns `ERR_NOT_FOUND` on the first missing identifier. Identifiers carried in the request body (the `agreement_id` on declaration creation, the `declaration_id` on document attachment, the `filing_id` on inspection-case creation, the `target_entity_id` on an external event) are also resolved and the same `ERR_NOT_FOUND` is returned with HTTP 404 if the referenced resource does not exist.

### 2.7. Precision, Currency, and Rounding

All monetary fields are stored and returned with two decimal places. The rounding mode is half-up — the conventional commercial rounding where exactly 0.005 rounds away from zero. The multi-step tariff pipeline (described in §3) pins the evaluation order so that intermediate rounded values feed downstream stages: a per-line-item currency conversion is rounded to two decimals; the tariff is then computed and rounded once at the end of its own formula; the value-added tax is computed off the already-rounded tariff and rounded; the consumption tax is computed off the same already-rounded tariff (not off the VAT) and rounded. Re-deriving any intermediate amount at higher precision inside a downstream formula is not permitted — the chain of rounds is the contract.

Currency conversion uses two snapshot tables. The declared currency of a declaration is converted to the settlement currency (the agreement client's `default_settlement_currency`) using a per-declaration `fx_rate_to_settlement` snapshot captured at pre-validation; when the declared and settlement currencies coincide, that rate is 1.0. The broker fee, denominated in the agreement currency, is converted first to the declared currency through a fixed agreement-to-declared rate table, then to the settlement currency through the same `fx_rate_to_settlement` snapshot. Five currencies are supported throughout: `USD`, `EUR`, `CNY`, `JPY`, and `GBP`.

### 2.8. Cascading Side Effects, Version Pinning, and Audit Logging

Many transitions in this system mutate more than the entity in the URL. The single most important rule is that every state-changing action writes an `AuditLog` row with `entity_type` set to one of `DECLARATION`, `SETTLEMENT`, `FILING`, `INSPECTION_CASE`, or `AGREEMENT`, with `entity_id` set to the affected resource's id, and with `event_type` drawn from `STATE_TRANSITION`, `FIELD_CHANGE`, `ADVANCE_PAID`, `REIMBURSED`, `AMENDMENT_FILED`, and `VOUCHER_DELIVERED`. The audit row's `actor_role` carries the `X-User-Role` value, the `actor_id` carries the `X-User-ID` value (or the literal string `system` for transitions triggered by clock advance or external events), and the `payload` records the event-specific snapshot — for a `STATE_TRANSITION` it carries the from/to states, for a `FIELD_CHANGE` it carries the field name and old/new values, and for an `ADVANCE_PAID` or `REIMBURSED` event it carries the amount and currency.

A successful mutation refreshes the target's `updated_at` and bumps its `version`. Cascade rules across entities are described in §3 alongside the workflow that produces them — declaration release creates a settlement, inspection penalty creates a settlement that includes the penalty, declaration withdrawal voids a provisional or final settlement and emits a logistics return-shipment event, and so on. Each cascaded mutation is itself an auditable event and produces its own `AuditLog` row.

Two version-pinning relationships exist between entities to detect mid-workflow drift. On the agreement, `pinned_fee_schedule_version` is set to the agreement's own `version` at the moment the agreement transitions to `ACTIVE`; subsequent edits to the agreement's `fee_schedule` would change the agreement's `version` but the snapshot remains for accounting purposes. On the declaration, `pinned_agreement_version` is set to the parent agreement's current `version` at the moment the declaration transitions to `PRE_VALIDATED`; at file time, the server compares this snapshot to the agreement's current `version`, and any mismatch — indicating that the agreement was mutated between pre-validate and file — is rejected with `ERR_AGREEMENT_VERSION_DRIFT`. Amending a declaration clears `pinned_agreement_version` so that the next pre-validate re-snapshots it.

### 2.9. Segregation of Duties

Two pairs of operations must be performed by different individuals. The first pair is pre-validate and file: a `DocReviewer` who advances a declaration to `PRE_VALIDATED` cannot then act as the `FilingOfficer` on the same declaration's file transition. The second pair is file and advance: the `FilingOfficer` who files a declaration cannot then act as the `SettlementOfficer` who advances the resulting settlement. Both violations return `ERR_SEGREGATION_OF_DUTIES` with HTTP 403. The check is conducted by comparing `X-User-ID` values as opaque strings; the audit log retains the prior actor identifier on the relevant transitions so this comparison is always available.

### 2.10. Validation Priority

When more than one validation could apply to a single request, the server evaluates them in a fixed priority order so that the surface error reflects the deepest problem rather than a downstream symptom. Authentication checks for `X-User-Role` and `X-User-ID` fire first, followed by role authorization, followed by left-to-right path existence and body-reference existence, followed by the optimistic-concurrency `version` check, followed by state preconditions (and the specific state guards `ERR_SETTLEMENT_HAS_ADVANCE` on withdrawal and `ERR_INVALID_STATE` on advancing a withdrawn declaration), followed by segregation-of-duties and document-safety checks (authenticity flagging, missing import licence, missing dangerous-goods declaration), followed by business-consistency checks (document completeness and consistency, declared-value flagging, manifest match, agreement fee-schedule validity), followed by business-temporal checks (agreement validity window, query deadline, auto-expiry block), followed by referential checks (agreement version drift, amendment cap, inspection-rejection amendability, scope-of-service), followed by fiscal checks (zero-amount settlement, bank-debit amount), with input-format validation evaluated last. The implication for the implementer is that `ERR_DOC_AUTHENTICITY_FLAGGED` outranks `ERR_DOC_INCOMPLETE`, which outranks `ERR_DECLARED_VALUE_FLAGGED`, which outranks `ERR_AGREEMENT_VERSION_DRIFT`, which outranks `ERR_INVALID_INPUT`; the segregation-of-duties pair-checks outrank document-completeness and consistency; and the document-safety triad (authenticity, license, dangerous-goods) is checked before document-completeness so that a flagged authenticity surfaces ahead of a still-missing core document.

### 2.11. Concurrency Race Outcomes

Four cross-request races are specified for this system, each with a guaranteed serialization point and a specific loser error. When two `FilingOfficer` operators simultaneously attempt to file the same `PRE_VALIDATED` declaration, the server serializes on Filing creation under the declaration: exactly one succeeds, and the loser receives `ERR_FILING_ALREADY_EXISTS` with HTTP 409. When a `RELEASE` customs response and a query-response action race for the same `FILED`/`QUERIED` filing, the server serializes on the filing's `response_type` field, and the loser is rejected with `ERR_INVALID_STATE` and HTTP 409 because the precondition on its target state no longer holds. When two `SettlementOfficer` operators concurrently attempt to advance the same `FINAL` settlement, the server serializes on `advance_paid_at` and the loser receives `ERR_SETTLEMENT_ALREADY_ADVANCED` with HTTP 409. When declaration withdrawal races with settlement advance on the same declaration, the server serializes on the settlement's `status` field; if advance wins first, the subsequent withdrawal returns `ERR_SETTLEMENT_HAS_ADVANCE` with HTTP 409, and if withdrawal wins first, the subsequent advance returns `ERR_INVALID_STATE` with HTTP 409. Finally, two `ClientUser` operators submitting the sign action on the same `AWAITING_SIGNATURE` agreement serialize on `signed_at` and the loser receives `ERR_INVALID_STATE` with HTTP 409.

### 2.12. External Events and the Test-Driving Clock

Three external systems drive transitions through asynchronously-emitted events: the customs single window emits customs responses, the inspection-and-quarantine authority emits inspection notices, and the bank confirms debits. A logistics carrier additionally drops manifests and receives return-shipment dispatch notices. All inbound events are funnelled through a single emit-event capability whose body carries the originating `source_system` (one of `SINGLE_WINDOW`, `INSPECTION_QUARANTINE`, `BANK`, or `LOGISTICS`), the `event_type` (one of `CUSTOMS_RESPONSE`, `MANIFEST_DROPPED`, `INSPECTION_NOTICE`, `BANK_DEBIT_CONFIRMED`, or `RETURN_SHIPMENT_DISPATCHED`), the `target_entity_type` (one of `FILING`, `DECLARATION`, `SETTLEMENT`, or `INSPECTION_CASE`), the `target_entity_id`, and an event-specific `payload` object. A `processed_at` timestamp is set when the event is received. The emit endpoint is restricted to `SystemAdmin` and, on success, returns HTTP 202 alongside the recorded `ExternalEvent` resource.

The system clock is exposed through an admin-only test-driving capability that advances the logical clock to a supplied `to_timestamp` instant. The response carries the new `now` plus the count of `transitions_triggered` by the advance. Clock advance is the trigger for three deferred actions: auto-expiring agreements whose `valid_until` is crossed (subject to the agreement-has-open-declarations guard), failing a queried declaration whose `query_due_at` is crossed without a query response, and refreshing the running late-interest amount on advanced settlements past their `reimbursement_due_at`.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Consignor and Drafting the Commission Agreement

The relationship begins when a `BrokerOps` operator records a consignor as a `ClientCompany`. The intake captures the consignor's `legal_name` and `tax_id` — both unique across non-archived clients and limited to 200 and 40 characters respectively — together with their ISO 3166-1 alpha-2 `country_code` (exactly two uppercase letters), a `contact_email` used for missing-document follow-up, and a `default_settlement_currency` from the five-currency set `USD`/`EUR`/`CNY`/`JPY`/`GBP`. A newly recorded client lands in `ACTIVE` `status`; an `ARCHIVED` client is excluded from uniqueness checks on `legal_name` and `tax_id`. Patching a client may update `legal_name`, `contact_email`, `default_settlement_currency`, and `status` — the `tax_id` is immutable once set.

With a client on file, the broker drafts the commission agreement — a binding contract that sets which services the broker is authorized to perform, what each service costs, when the engagement starts and ends, and how late reimbursement is priced. A `BrokerOps` operator creates the agreement carrying the parent `client_id`, a `scope_of_service` array (a non-empty subset of the codes `DECLARATION`, `INSPECTION`, `TARIFF_ADVANCE`, `RETURN_SHIP`, and `AMENDMENT`), a `fee_schedule` object mapping each in-scope service code to a non-negative numeric fee, an `agreement_currency` from the five-currency set, an inclusive `valid_from` instant, an exclusive `valid_until` instant which must be strictly greater than `valid_from`, and a `late_interest_daily_rate_bps` integer in the range zero to one thousand (basis points per day, where one basis point equals one hundredth of one percent). If this is a renewal, the request carries `renewed_from_agreement_id`; otherwise the field is null. An agreement is born in `DRAFT` `status` with `signed_at` and `signature_token` and `pinned_fee_schedule_version` all initialised to null and `terminated_reason` initialised to null.

The fee-schedule structure is validated at creation and at request-signature: every key in `fee_schedule` must equal some entry in `scope_of_service`, and every entry in `scope_of_service` must appear as a key in `fee_schedule`. Any mismatch — a service in scope without a fee, or a fee for a service not in scope — is rejected with `ERR_FEE_SCHEDULE_INVALID` and HTTP 422.

### 3.2. Signature, Activation, Renewal, and Termination

Once the broker is satisfied with the draft, a `BrokerOps` operator initiates signature. The agreement must still be in `DRAFT`, its parent `ClientCompany` must be `ACTIVE`, its `fee_schedule` keys must match `scope_of_service` exactly, and the validity window must satisfy `valid_from` strictly less than `valid_until`. On success the agreement advances from `DRAFT` to `AWAITING_SIGNATURE` and the server mints an opaque `signature_token` and persists it on the record.

The client then exercises their exclusive sign action. A `ClientUser` submits the `signature_token` they received together with the current `version`; the server verifies that the submitted token matches the stored `signature_token` and that the current clock is still strictly before `valid_until`. On success the agreement advances from `AWAITING_SIGNATURE` to `ACTIVE`, `signed_at` is set to the current instant, and `pinned_fee_schedule_version` is snapshotted to the agreement's post-increment `version` so that downstream tariff-advance and broker-fee logic can reference the exact fee table that was in force at signing. If the agreement was a renewal — that is, `renewed_from_agreement_id` is non-null — the predecessor agreement's `status` is set to `RENEWED` as a single atomic side effect.

Termination is reachable from either `DRAFT` or `ACTIVE`. A `BrokerOps` operator initiates it, providing a `terminated_reason` from the set `CLIENT_REQUEST`, `BREACH`, or `REGULATORY`. From `DRAFT` the transition has no further precondition; from `ACTIVE` the agreement is additionally guarded so that termination is blocked if any declaration under it is still in any of the non-terminal declaration states `DRAFT`, `DOCS_PENDING`, `PRE_VALIDATED`, `FILED`, `QUERIED`, `INSPECTING`, or `AMENDING`. The transition writes a `FIELD_CHANGE` audit row capturing the new `terminated_reason` alongside the `STATE_TRANSITION` row.

Auto-expiry is the system's other terminal path. When the clock advances past an active agreement's `valid_until`, the server attempts the transition to `EXPIRED`; the transition is allowed only when no declaration under the agreement is in any of the non-terminal declaration states listed above. If any such declaration exists, the system holds the agreement in `ACTIVE` until those declarations settle or are rejected, and the original blocking signal is captured as `ERR_AGREEMENT_HAS_OPEN_DECLARATIONS` with HTTP 409 in the clock-advance result trace. Two concurrent client-sign attempts on the same `AWAITING_SIGNATURE` agreement serialise on `signed_at`: exactly one succeeds and the loser receives `ERR_INVALID_STATE`.

### 3.3. Drafting a Declaration and Reviewing Declared Value

A `DeclarationOfficer` (shared with `BrokerOps`) opens a declaration by filing the initial intake against an active agreement. The request payload carries the parent `agreement_id`, the destination `jurisdiction_code` (one of `CN`, `US`, `EU`, `JP`, or `GB`), a carrier-supplied `shipment_reference` (1..60 characters, unique per `agreement_id` among non-`WITHDRAWN` declarations), an `hs_code` (numeric, of length six, eight, or ten depending on jurisdiction), a two-letter `country_of_origin`, an optional `trade_agreement_code` from the set `NONE`, `RCEP`, `USMCA`, `EU_GSP`, or `CPTPP` (defaulting to `NONE`, which means the most-favoured-nation general tariff applies), a non-negative `declared_value_amount` carrying at most two decimal places, and the matching `declared_currency`. The parent agreement must be in `ACTIVE` `status` with the current instant in the inclusive-exclusive range from `valid_from` to `valid_until` — otherwise the request is rejected with `ERR_AGREEMENT_NOT_ACTIVE` and HTTP 409. The string `DECLARATION` must also appear in the agreement's `scope_of_service`; otherwise the create returns `ERR_SERVICE_OUT_OF_SCOPE`.

A newly created declaration is in `DRAFT` `status`, with `declared_value_review_status` initialised to `PENDING`, `amendment_count` initialised to zero, and `form_payload`, `fx_rate_to_settlement`, `rejection_reason_code`, and `pinned_agreement_version` all initialised to null. As a side effect of creation, and again as a side effect of any patch that changes `declared_value_amount`, the server runs a declared-value review heuristic against a reference-price table keyed by jurisdiction and the first four digits of `hs_code`. The first step converts the declared amount into the settlement currency by multiplying `declared_value_amount` by `fx_rate_to_settlement` (using 1.0 when the rate is not yet pinned) and rounding the product to two decimals. The server then looks up the reference price for the (`jurisdiction_code`, first four digits of `hs_code`) pair; if no reference exists for the pair, `declared_value_review_status` is set to `ACCEPTED`. When a reference exists, the server computes the absolute difference between the rounded base value and the reference, divides by the reference to obtain a deviation ratio, and sets `declared_value_review_status` to `ACCEPTED` when the deviation is at most twenty-five percent and to `FLAGGED` when the deviation exceeds twenty-five percent. The boundary at exactly twenty-five percent resolves to `ACCEPTED`. The reference table contains an entry of eight hundred (in settlement-currency units) for HS prefix `8517` across all five jurisdictions, plus an entry of fifty for the (`CN`, `2208`) pair; other (jurisdiction, prefix) pairs are absent and therefore default to `ACCEPTED`.

A patch action on the declaration is restricted to the `DeclarationOfficer` role and is accepted only while the declaration is in `DRAFT`, `DOCS_PENDING`, or `AMENDING`. The mutable fields are `declared_value_amount`, `hs_code`, `country_of_origin`, and `trade_agreement_code`. A change to `declared_value_amount` triggers a fresh declared-value review per the algorithm above. As with all mutating endpoints, the optional `version` field protects against lost updates.

### 3.4. Document Intake, Authenticity Screening, and Consistency

When the operator is ready to gather supporting paperwork, a `DeclarationOfficer` invokes the request-documents action, which advances the declaration from `DRAFT` to `DOCS_PENDING`. The transition is allowed only when `hs_code`, `country_of_origin`, `declared_value_amount`, and `declared_currency` are all populated, the parent agreement is `ACTIVE`, and `DECLARATION` is in `scope_of_service`. The side effect of this transition is that for each of the four core document types — `COMMERCIAL_INVOICE`, `PACKING_LIST`, `BILL_OF_LADING`, `CONTRACT` — that does not yet have a corresponding `ShipmentDocument`, the server creates a stub record with `follow_up_requested_at` set to the current instant; this is the audit trail showing that the operator has explicitly asked the client to provide the missing document.

Each `ShipmentDocument` is attached through a dedicated capability available to both `DeclarationOfficer` and `ClientUser`. The request body carries the parent `declaration_id`, a `doc_type` from the seven-value enumeration `COMMERCIAL_INVOICE`, `PACKING_LIST`, `BILL_OF_LADING`, `CONTRACT`, `IMPORT_LICENSE`, `INSPECTION_CERT`, or `DANGEROUS_GOODS_DECL`, a `storage_uri` (1..500 characters, typically an opaque object-store URI), and — for documents that carry a numeric total such as commercial invoices or packing lists — a `declared_total_value` and `declared_total_currency` pair. Both numeric fields are nullable and default to null when not applicable. On creation, the server runs a provisional authenticity screen and sets `authenticity_score` and `authenticity_status`; `authenticity_status` is one of `UNSCREENED`, `ACCEPTED`, or `FLAGGED` and the score is a decimal in the closed range zero to one.

The authenticity score is the weighted sum of three signals each valued at either zero or one (with one half-credit case): the first signal contributes 1.0 if the current document declares a total value and another sibling document of the partner type (`COMMERCIAL_INVOICE` versus `PACKING_LIST`) under the same declaration carries a matching total within 0.5 percent of the larger of the two figures, else 0.0; the second signal contributes 1.0 if `declared_total_currency` equals the declaration's `declared_currency` and 0.0 otherwise; the third signal contributes 1.0 if `storage_uri` matches the pattern of one or more lowercase scheme letters followed by `://` and at least one character, else 0.5. The signals are weighted at 0.5, 0.3, and 0.2 respectively, and their weighted sum is rounded half-up to two decimal places to produce `authenticity_score`. The verdict at the threshold is fixed: a score of at least 0.70 yields `authenticity_status` of `ACCEPTED`, a score strictly below 0.70 yields `FLAGGED`, and the boundary value 0.70 itself resolves to `ACCEPTED`.

The provisional screen is run only against the siblings that exist at the moment of insert; if a later sibling arrives that would have improved the score, the prior document's score is not automatically recomputed. To force a recomputation, a `DocReviewer` invokes the screen capability on the document, which re-runs the same three-signal weighted score against the full current set of sibling documents and updates `authenticity_score` and `authenticity_status` accordingly. A document that was `FLAGGED` on insert can flip to `ACCEPTED` after later siblings arrive and screen is invoked.

### 3.5. Pre-validation, Cross-Document Consistency, and Form Generation

When the operator believes the document set is complete, a `DocReviewer` advances the declaration from `DOCS_PENDING` to `PRE_VALIDATED` (the same action applies from `AMENDING` to `PRE_VALIDATED` on a re-pre-validate path after amendment). The pre-validate gate enforces a layered set of checks. First, in descending priority, no `ShipmentDocument` under the declaration may have `authenticity_status` of `FLAGGED` — any flagged document blocks the transition with `ERR_DOC_AUTHENTICITY_FLAGGED`. Second, jurisdiction-and-HS-driven document requirements must be satisfied: when `hs_code` starts with `28` or `29`, or when `jurisdiction_code` is `CN` and the first two characters of `hs_code` are `29`, an `IMPORT_LICENSE` document must exist, or the transition is rejected with `ERR_DOC_MISSING_LICENSE`; when `hs_code` starts with `2208`, `2402`, or `2710`, a `DANGEROUS_GOODS_DECL` document must exist, or the transition is rejected with `ERR_DOC_MISSING_DG`. Third, the four core documents — `COMMERCIAL_INVOICE`, `PACKING_LIST`, `BILL_OF_LADING`, and `CONTRACT` — must all exist for the declaration, or the transition is rejected with `ERR_DOC_INCOMPLETE`. Fourth, cross-document consistency is enforced between the commercial invoice and the packing list: when both are present in the same currency, the absolute difference between their `declared_total_value` figures must be at most 0.5 percent of the larger of the two — in other words, the larger minus the smaller divided by the larger must not exceed 0.005, with the boundary at exactly 0.5 percent treated as acceptable; otherwise the transition is rejected with `ERR_DOC_INCONSISTENT`. Fifth, the declared-value review must have produced an `ACCEPTED` `declared_value_review_status` (a `FLAGGED` status blocks both pre-validation and filing — see §3.6).

On success, the pre-validate transition runs three side effects. The first computes the snapshot `fx_rate_to_settlement` from the declared currency to the agreement client's settlement currency (1.0 when the two currencies match). The second generates the jurisdiction-specific `form_payload` by selecting the template keyed by `jurisdiction_code` and filling it with declaration fields. The third snapshots `pinned_agreement_version` to the parent agreement's current `version`, which becomes the drift sentinel at file time. The audit log records both the `STATE_TRANSITION` and the `FIELD_CHANGE` covering `form_payload` and `fx_rate_to_settlement`.

### 3.6. Filing, Manifest Matching, and Customs Responses

A `FilingOfficer` advances the declaration from `PRE_VALIDATED` to `FILED`. Two preconditions guard the transition. First, `pinned_agreement_version` must equal the parent agreement's current `version` — any drift between pre-validate and file indicates that the agreement has been mutated in the interim and the declaration must be re-pre-validated; the rejection code is `ERR_AGREEMENT_VERSION_DRIFT`. Second, the segregation-of-duties pair fires: the `X-User-ID` performing the file action must differ from the `X-User-ID` that performed the prior pre-validate transition, otherwise `ERR_SEGREGATION_OF_DUTIES` is returned. A further business-consistency guard requires `declared_value_review_status` not to be `FLAGGED` — a flagged declared value blocks filing with `ERR_DECLARED_VALUE_FLAGGED`. On success, the server creates a `Filing` carrying the parent `declaration_id`, a freshly-minted `single_window_ref` UUID, `submitted_at` set to the current instant, `response_type` initialised to `AWAITING`, `manifest_match_status` initialised to `UNMATCHED`, and the `is_amendment` flag set to true exactly when the declaration's `amendment_count` is greater than zero. An `AMENDMENT_FILED` audit row is emitted when `is_amendment` is true.

Two simultaneous filings on the same `PRE_VALIDATED` declaration serialise on `Filing` creation: exactly one succeeds and the loser receives `ERR_FILING_ALREADY_EXISTS`.

After filing, the declaration is in `FILED` and the `Filing` is in `AWAITING`. The carrier's manifest event is the first input that can change this state. When the logistics system emits an event with `source_system` set to `LOGISTICS` and `event_type` set to `MANIFEST_DROPPED`, the server compares the event payload's shipment reference and HS code to the declaration's `shipment_reference` and `hs_code`. The filing's `manifest_match_status` is set to `MATCHED` if both values agree exactly; otherwise it is set to `MISMATCHED`. The filing's state stays `AWAITING` and the declaration's state is unaffected. A `MISMATCHED` manifest is recorded as a `FIELD_CHANGE` audit row and becomes the gate that blocks a subsequent customs release.

The customs single window then emits a `CUSTOMS_RESPONSE` event with `payload.response_type` of `QUERY`, `INSPECT`, `RELEASE`, or `REJECT`, each of which drives a distinct branch out of `FILED`. A `QUERY` response advances the declaration to `QUERIED` and sets the filing's `response_type` to `QUERY`, `response_received_at` to the current instant, and `query_due_at` to the current instant plus forty-eight hours. An `INSPECT` response advances the declaration to `INSPECTING` and sets the filing's `response_type` to `INSPECT`. A `RELEASE` response advances the declaration to `RELEASED` and sets the filing's `response_type` to `RELEASE` — but only if the filing's `manifest_match_status` is `MATCHED`; an attempt to process a `RELEASE` against an `UNMATCHED` or `MISMATCHED` manifest is rejected with `ERR_MANIFEST_MISMATCH`. A `REJECT` response advances the declaration to `REJECTED`, sets the filing's `response_type` to `REJECT`, sets `rejection_reason_code` to the value carried in the payload's reason field, and creates a `RejectionRecord` carrying the parent `declaration_id`, the same `rejection_reason_code`, `archived_at` set to the current instant, `prior_amendment_count` snapshotted from the declaration's `amendment_count`, and an optional operator-supplied `free_text_note` (up to 500 characters). All four branches require the filing's `response_type` to still be `AWAITING` at the moment the event arrives; a customs response received against a non-`AWAITING` filing is rejected with `ERR_INVALID_STATE` (this is the loser-side serialization outcome for a customs-release-versus-respond-query race).

When the declaration is in `QUERIED`, a `FilingOfficer` may submit a query response with the originating `response_note` and the optional `version`. The transition is allowed only when the current instant is strictly before `query_due_at` and the filing's `response_type` is still `QUERY`; an attempt after the deadline is rejected with `ERR_QUERY_DEADLINE_PASSED`. The success path sets `query_response_at` to the current instant and resets the filing's `response_type` to `AWAITING` so that customs may evaluate again. If the clock advances past `query_due_at` without a query response, the system automatically transitions the declaration from `QUERIED` to `REJECTED`, sets `rejection_reason_code` to `OTHER`, and creates a `RejectionRecord` exactly as it would for an explicit `REJECT` response.

### 3.7. Inspection Scheduling, Sample Coordination, and Outcomes

When customs returns an `INSPECT` response, the declaration moves to `INSPECTING` and the system expects an `InspectionCase` to be created. An `InspectionOfficer` (shared with `BrokerOps`) creates the case carrying the parent `filing_id`, a `warehouse_code` (1..40 characters identifying the bonded warehouse), the customs-supplied `scheduled_at` instant (the inspection window runs from `scheduled_at` for four hours), and an optional `sample_required` boolean defaulting to false. A newly-created case is in `PENDING` `outcome` with `sample_provided_at` set to null and `penalty_amount` initialised to zero. If `sample_required` is true, the client must confirm sample provision before the case can be closed; a `ClientUser` (or `BrokerOps`) invokes the sample-provision capability, which sets `sample_provided_at` to the current instant.

The `InspectionOfficer` records the outcome through a single action carrying the `outcome` value (`RELEASE`, `DETENTION`, or `PENALTY`), an optional `penalty_amount` in `declared_currency` (required when `outcome` is `PENALTY` — it must be strictly positive), and the customs-issued `post_inspection_doc_uri`. The action is accepted only when the case's `outcome` is still `PENDING`, when the current instant is at or after `scheduled_at`, and — when `sample_required` is true — when `sample_provided_at` is non-null. A `RELEASE` outcome advances the declaration from `INSPECTING` to `RELEASED` and cascades to settlement creation in `FINAL` `status` with `penalty_amount` of zero. A `DETENTION` outcome advances the declaration from `INSPECTING` to `REJECTED`, sets `rejection_reason_code` to `INSPECTION_FAILED`, creates a `RejectionRecord`, but does not create a settlement. A `PENALTY` outcome advances the declaration from `INSPECTING` to `REJECTED`, sets `rejection_reason_code` to `INSPECTION_FAILED`, creates a `RejectionRecord`, and cascades to settlement creation in `FINAL` `status` with `penalty_amount` populated through the penalty-conversion calculation described in §3.8. Each cascade writes its own `STATE_TRANSITION` audit row.

A declaration rejected due to `INSPECTION_FAILED` cannot be amended — amendment is reserved for paperwork-driven rejections, and inspection failures must be withdrawn instead. An attempt to amend an inspection-failed declaration is rejected with `ERR_INSPECTION_REJECTION_NOT_AMENDABLE`.

### 3.8. Settlement Creation: Tariff, VAT, Consumption Tax, and Penalty Conversion

The cascade from `RELEASED` (whether reached via the post-filing `RELEASE` response or via the post-inspection `RELEASE` outcome) creates a `Settlement` carrying the parent `declaration_id` and populates four computed amounts plus the broker fee, all denominated in `settlement_currency` (a snapshot of the client's `default_settlement_currency` taken at creation). The pipeline is strictly ordered — tariff first, then VAT off the already-rounded tariff, then consumption tax off the same already-rounded tariff (not off the VAT), then the penalty conversion if applicable, then the broker fee.

The tariff calculation begins with a per-line-item currency conversion: the declared amount is converted into the settlement currency by multiplying `declared_value_amount` by `fx_rate_to_settlement` and rounding the product half-up to two decimals to produce the base value. The duty rate is then selected. When `trade_agreement_code` is `NONE` (or when the declared `country_of_origin` is not eligible under the named agreement for this jurisdiction), the rate comes from the most-favoured-nation table: for jurisdiction `CN` the rate is 0.10 for general goods and 0.05 for HS prefix `8517`; for `US` it is 0.08 and 0.04 respectively; for `EU` it is 0.12 and 0.06; for `JP` it is 0.09 and 0.045; for `GB` it is 0.10 and 0.05. When a preferential agreement applies and the origin is eligible, the rate comes from the preferential table: under `RCEP` the rate is 0.05 (default) or 0.02 (HS `8517`) for `CN`, and 0.04 or 0.02 for `JP`; under `USMCA` the rate for `US` is 0.03 (default) or 0.015 (HS `8517`); under `EU_GSP` the rate for `EU` is 0.06 (default) or 0.03 (HS `8517`); under `CPTPP` the rate for `JP` is 0.035 (default) or 0.015 (HS `8517`). A tiered surcharge then applies as a function of the base value: a base value at most 10000 carries a tier factor of 1.00; a base value strictly greater than 10000 and at most 50000 carries a tier factor of 1.05 (a five-percent surcharge over the range); a base value strictly greater than 50000 carries a tier factor of 1.10 (a ten-percent surcharge). The final tariff is the base value multiplied by the duty rate multiplied by the tier factor, rounded half-up once at the very end to two decimal places.

The VAT is computed off the already-rounded tariff. The VAT base is the sum of the base value and the tariff amount, and the VAT amount is that base multiplied by the jurisdiction's VAT rate — 0.13 for `CN`, 0.00 for `US`, 0.21 for `EU`, 0.10 for `JP`, and 0.20 for `GB` — and rounded half-up to two decimal places.

The consumption tax applies only to specific jurisdiction-and-HS-prefix pairs. The applicable pairs and rates are (`CN`, `2208`) at 0.20, (`JP`, `2208`) at 0.15, (`US`, `2402`) at 0.30, and (`GB`, `2402`) at 0.25; pairs outside this set produce a consumption tax of zero. When a pair is in the table, the consumption-tax base is the sum of the base value and the tariff amount (the VAT is excluded), and the tax is the base multiplied by the consumption-tax rate, rounded half-up to two decimals. A boundary applies: if the consumption-tax base is strictly less than 100 the tax is zero, and if it is at least 100 the tax is computed. The boundary value 100 itself triggers taxation.

The penalty amount on the settlement, when the cascade is driven by an inspection `PENALTY` outcome, is the inspection case's `penalty_amount` (denominated in `declared_currency`) multiplied by `fx_rate_to_settlement` and rounded half-up to two decimals.

### 3.9. Broker Fee Composition

The broker's own service fee is computed as a side effect of settlement creation. The set of services consumed by the declaration is computed first: `DECLARATION` is always present; `INSPECTION` is added if an `InspectionCase` exists for the declaration; `TARIFF_ADVANCE` is added when `advance_paid_amount` is strictly positive (always the case for `FINAL` settlements that proceed to advance); and `AMENDMENT` is added when `amendment_count` is strictly positive, with the entry levied once per settlement regardless of how many amendment cycles have occurred. The raw total in the agreement's currency is the sum of `fee_schedule` entries for each consumed service. The conversion to settlement currency is a two-step path: the agreement-currency total is converted to the declared currency using a fixed agreement-to-declared rate table — the supported pairs include `(USD, USD)` at 1.00, `(USD, CNY)` at 7.20, `(USD, EUR)` at 0.92, `(USD, JPY)` at 150.0, `(USD, GBP)` at 0.78, `(CNY, CNY)` at 1.00, `(CNY, USD)` at 0.139, `(EUR, EUR)` at 1.00, `(EUR, USD)` at 1.08, `(JPY, JPY)` at 1.00, `(JPY, USD)` at 0.0067, `(GBP, GBP)` at 1.00, and `(GBP, USD)` at 1.28 — and the resulting declared-currency total is then multiplied by `fx_rate_to_settlement` to reach the settlement currency. The two multiplications and the sum are deferred-rounded: the product of the raw total, the agreement-to-declared rate, and `fx_rate_to_settlement` is rounded half-up to two decimal places exactly once at the end to produce `broker_fee_amount`. The result is written to the settlement record alongside the tariff, VAT, consumption-tax, and penalty fields.

### 3.10. Advance Funding, Late Interest, and Reimbursement

A `Settlement` born from the release cascade is created in `FINAL` `status` (the `PROVISIONAL` value exists in the enum so that audit logs and tooling can refer to a pre-creation moment, but no row is ever observably persisted in `PROVISIONAL` — the cascade transitions directly to `FINAL` in a single atomic step). A `SettlementOfficer` then funds the broker advance through a dedicated action. Two preconditions guard the transition: the sum of `tariff_amount`, `vat_amount`, `consumption_tax_amount`, and `penalty_amount` must be strictly positive (a settlement whose entire bill is zero cannot be advanced and is rejected with `ERR_SETTLEMENT_ZERO_AMOUNT`); and the acting `X-User-ID` must differ from the `X-User-ID` of the `FilingOfficer` who filed the declaration, otherwise the transition is rejected with `ERR_SEGREGATION_OF_DUTIES`. A further state guard requires the parent declaration's `status` not to be `WITHDRAWN` — a withdrawn declaration cannot be advanced against and is rejected with `ERR_INVALID_STATE`. On success, the settlement transitions from `FINAL` to `ADVANCED`, `advance_paid_amount` is set to the sum tariff + VAT + consumption tax + penalty, `advance_paid_at` is set to the current instant, and `reimbursement_due_at` is set to the current instant plus seven days. The transition emits both a `STATE_TRANSITION` audit row and an `ADVANCE_PAID` row carrying the amount and currency.

Two simultaneous advance attempts on the same `FINAL` settlement serialise on `advance_paid_at`: exactly one wins and the loser receives `ERR_SETTLEMENT_ALREADY_ADVANCED`.

Late-reimbursement interest accrues only once the current instant is strictly past `reimbursement_due_at`. While the current instant is at or before `reimbursement_due_at`, `late_interest_amount` is zero. Past the deadline, the number of days late is the ceiling of the elapsed seconds divided by 86400 — a partial day still counts as a full day, so the moment the instant exceeds the deadline by even one microsecond, one full day of interest is owed. The daily rate is `late_interest_daily_rate_bps` divided by 10000 (since one basis point is one ten-thousandth). The simple-interest formula multiplies `advance_paid_amount` by the daily rate by the days-late count, with a single half-up round to two decimals at the very end — interest does not compound. Reads of an advanced settlement that has not yet been reimbursed report the current snapshot of this running estimate without persisting it, and clock advance is the trigger that refreshes the estimate.

Reimbursement is event-driven. When the bank emits a `BANK_DEBIT_CONFIRMED` event targeting the settlement, the server compares the payload's amount to the sum of `advance_paid_amount` and the current running `late_interest_amount`. An exact match advances the settlement from `ADVANCED` to `REIMBURSED`, sets `reimbursed_at` to the current instant, computes `late_interest_amount` one final time at the reimbursement moment and freezes the value, generates `voucher_uri` by concatenating the literal string `voucher://` with the settlement's `id`, and emits both a `REIMBURSED` audit row and a `VOUCHER_DELIVERED` audit row. A mismatch — payload amount differing from the expected sum — is rejected with `ERR_BANK_AMOUNT_MISMATCH` and HTTP 422.

### 3.11. Rejection, Amendment, and Withdrawal

A rejected declaration's downstream path depends on its `rejection_reason_code`. For paperwork-driven rejections — codes other than `INSPECTION_FAILED` — a `DeclarationOfficer` may amend, advancing the declaration from `REJECTED` to `AMENDING`. The amendment transition increments `amendment_count` by one, clears `rejection_reason_code`, and clears `pinned_agreement_version` (forcing the next pre-validate to re-snapshot the agreement's version). The amendment cap is hard: a declaration whose `amendment_count` has already reached 3 cannot amend further and is rejected with `ERR_AMENDMENT_CAP_REACHED`. After amendment, the same `DOCS_PENDING → PRE_VALIDATED` checks apply and the declaration retraces the path: pre-validate, file, and any subsequent customs response.

Withdrawal is reachable from `DRAFT` (when no filing yet exists) and from `REJECTED` (when a `RejectionRecord` exists for the declaration). It is performed by a `BrokerOps` operator and is blocked when any `Settlement` for the declaration is in `ADVANCED` or `REIMBURSED` `status`; the rejection code is `ERR_SETTLEMENT_HAS_ADVANCE`. On success the declaration moves to `WITHDRAWN`. If a `Settlement` exists for the declaration in `PROVISIONAL` or `FINAL` `status`, it is voided (status set to `VOIDED`) as a cascade. The transition also emits an `ExternalEvent` to `LOGISTICS` with `event_type` of `RETURN_SHIPMENT_DISPATCHED` so the carrier can begin return-shipment coordination. The race between withdrawal and advance on the same declaration serialises on the settlement's `status`: if advance wins, the subsequent withdrawal returns `ERR_SETTLEMENT_HAS_ADVANCE`; if withdrawal wins, the subsequent advance returns `ERR_INVALID_STATE`.

A `RejectionRecord` is the archival receipt for any rejection. It carries `declaration_id`, `rejection_reason_code` (drawn from the enumeration `HS_MISMATCH`, `VALUE_UNDERSTATED`, `MISSING_LICENSE`, `INSPECTION_FAILED`, `MANIFEST_MISMATCH`, or `OTHER`), `archived_at`, an optional operator-supplied `free_text_note` of up to 500 characters describing the context, and `prior_amendment_count` snapshotted from the declaration at the moment of archival. Rejection records are listable for compliance analytics with optional filters on `rejection_reason_code` and `declaration_id`. They are minimal records with `id` and `created_at` only — they carry no `updated_at` and no `version`.

## 4. Endpoint Definitions

All endpoints in this system are mounted under `/customs`. Endpoints that create a new persisted resource — clients, agreements, declarations, documents, inspection cases — return HTTP 201; the external-event emit endpoint returns HTTP 202 to reflect the asynchronous-event semantics; all other endpoints, including state-transition actions, patches, and reads, return HTTP 200. Authentication and authorisation are enforced per §2.1, optimistic-concurrency `version` checks per §2.5, and the validation ordering of §2.10 determines which error surfaces when multiple checks would apply.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /customs/clients | Create a client company (consignor) | BrokerOps, SystemAdmin |
| GET | /customs/clients/{id} | Read client | BrokerOps, SystemAdmin, ClientUser |
| GET | /customs/clients | List clients | BrokerOps, SystemAdmin |
| PATCH | /customs/clients/{id} | Update mutable client fields | BrokerOps, SystemAdmin |
| POST | /customs/agreements | Create a commission agreement (DRAFT) | BrokerOps |
| GET | /customs/agreements/{id} | Read agreement | BrokerOps, DeclarationOfficer, FilingOfficer, SettlementOfficer, ClientUser, SystemAdmin |
| POST | /customs/agreements/{id}/request-signature | DRAFT → AWAITING_SIGNATURE; mint signature_token | BrokerOps |
| POST | /customs/agreements/{id}/sign | AWAITING_SIGNATURE → ACTIVE; client e-signs | ClientUser |
| POST | /customs/agreements/{id}/terminate | Terminate agreement (DRAFT or ACTIVE → TERMINATED) | BrokerOps |
| POST | /customs/declarations | Create declaration (DRAFT) | DeclarationOfficer, BrokerOps |
| GET | /customs/declarations/{id} | Read declaration | DeclarationOfficer, DocReviewer, FilingOfficer, SettlementOfficer, BrokerOps, ClientUser, SystemAdmin |
| GET | /customs/declarations | List declarations | DeclarationOfficer, DocReviewer, FilingOfficer, SettlementOfficer, BrokerOps, SystemAdmin |
| PATCH | /customs/declarations/{id} | Update mutable declaration fields (DRAFT, DOCS_PENDING, AMENDING only) | DeclarationOfficer |
| POST | /customs/declarations/{id}/request-documents | DRAFT → DOCS_PENDING; stub missing core docs | DeclarationOfficer |
| POST | /customs/declarations/{id}/documents | Attach a ShipmentDocument | DeclarationOfficer, ClientUser |
| POST | /customs/documents/{id}/screen | Re-run authenticity screening (final variant) | DocReviewer |
| POST | /customs/declarations/{id}/pre-validate | DOCS_PENDING → PRE_VALIDATED (or AMENDING → PRE_VALIDATED) | DocReviewer |
| POST | /customs/declarations/{id}/file | PRE_VALIDATED → FILED; submit to single window | FilingOfficer |
| POST | /customs/declarations/{id}/respond-query | QUERIED → FILED (back to AWAITING) | FilingOfficer |
| POST | /customs/declarations/{id}/amend | REJECTED → AMENDING (non-inspection rejections) | DeclarationOfficer |
| POST | /customs/declarations/{id}/withdraw | DRAFT or REJECTED → WITHDRAWN | BrokerOps |
| POST | /customs/inspection-cases | Create inspection case | InspectionOfficer, BrokerOps |
| POST | /customs/inspection-cases/{id}/provide-sample | Client confirms sample provision | ClientUser, BrokerOps |
| POST | /customs/inspection-cases/{id}/record-outcome | Record outcome (PENDING → RELEASE/DETENTION/PENALTY) | InspectionOfficer |
| GET | /customs/inspection-cases/{id} | Read inspection case | InspectionOfficer, BrokerOps, DeclarationOfficer, ClientUser, SystemAdmin |
| GET | /customs/settlements/{id} | Read settlement (live late interest) | SettlementOfficer, BrokerOps, ClientUser, SystemAdmin |
| GET | /customs/settlements | List settlements | SettlementOfficer, BrokerOps, SystemAdmin |
| POST | /customs/settlements/{id}/advance | FINAL → ADVANCED; fund tariff + VAT + CT + penalty | SettlementOfficer |
| GET | /customs/audit-log | List audit-log events | SystemAdmin, BrokerOps |
| GET | /customs/rejection-records | List rejection records | SystemAdmin, BrokerOps, DeclarationOfficer |
| POST | /customs/_events/emit | Emit an external event (drives system transitions) | SystemAdmin |
| POST | /customs/_clock/advance | Advance the logical clock for time-gated transitions | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_FILING_ALREADY_EXISTS | 409 |
| ERR_SETTLEMENT_ALREADY_ADVANCED | 409 |
| ERR_SETTLEMENT_HAS_ADVANCE | 409 |
| ERR_DOC_INCOMPLETE | 409 |
| ERR_DOC_INCONSISTENT | 409 |
| ERR_DOC_AUTHENTICITY_FLAGGED | 409 |
| ERR_DOC_MISSING_LICENSE | 409 |
| ERR_DOC_MISSING_DG | 409 |
| ERR_DECLARED_VALUE_FLAGGED | 409 |
| ERR_MANIFEST_MISMATCH | 409 |
| ERR_AGREEMENT_NOT_ACTIVE | 409 |
| ERR_AGREEMENT_VERSION_DRIFT | 409 |
| ERR_AGREEMENT_HAS_OPEN_DECLARATIONS | 409 |
| ERR_AMENDMENT_CAP_REACHED | 409 |
| ERR_INSPECTION_REJECTION_NOT_AMENDABLE | 409 |
| ERR_QUERY_DEADLINE_PASSED | 409 |
| ERR_SERVICE_OUT_OF_SCOPE | 409 |
| ERR_FEE_SCHEDULE_INVALID | 422 |
| ERR_SETTLEMENT_ZERO_AMOUNT | 409 |
| ERR_BANK_AMOUNT_MISMATCH | 422 |
| ERR_INVALID_INPUT | 422 |
