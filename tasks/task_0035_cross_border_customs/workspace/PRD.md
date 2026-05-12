# Cross-Border Customs API — Product Requirements Document

## 1. Introduction

Cross-border e-commerce moves merchandise across customs jurisdictions on timelines that retail customers expect to feel domestic. The customs clearance backbone described in this document coordinates the moving parts that make that experience possible: classifying each item against a regulator-maintained HS code library, aggregating an order into a customs declaration whose form template depends on the trade mode, computing tariffs and downstream taxes against rate tables that change with origin country and effective date, exchanging documents with a customs reviewer who may query, inspect, approve, or reject, and finally funneling tax payment, conditional or unconditional release, post-release amendments, and refunds through a single auditable pipeline. The system also acts as the integration hub between the platform and external counterparties — the Customs Single Window, the payment gateway, the logistics carrier, and the merchant's ERP — emitting synchronization events as state changes happen.

The product is built around three operator personas working from opposite sides of the customs counter — a cross-border platform agent who files declarations on behalf of importers, a government customs reviewer who decides whether goods clear, and a treasury operator who confirms payments and disburses refunds — plus the importer of record and a read-only auditor. Each persona's authority is narrow by design, because customs liability flows along role boundaries: a finance operator must never approve a declaration, and a declarant must never confirm their own payment. The API surface enforces these boundaries on every request, and every state change becomes part of an immutable audit trail that compliance auditors can replay without consulting the operating systems of any single counterparty.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP status 400. If the headers are present but the role named in `X-User-Role` is not authorized to invoke the requested endpoint per the role matrix, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` and HTTP status 403.

The five roles recognized by the system are `Declarant`, `CustomsOfficer`, `FinanceOfficer`, `Importer`, and `Auditor`. Two of these roles are entity-backed and three are opaque operator identifiers. When `X-User-Role` is `Declarant`, `X-User-ID` is the `id` of the acting `Declarant` entity; ownership checks on any declaration, refund, or query that references a declarant compare the resource's `declarant_id` to `X-User-ID`. When `X-User-Role` is `Importer`, `X-User-ID` is the `id` of the acting `Importer` entity; ownership checks on any order, declaration, or payment notice that references an importer compare the resource's `importer_id` (transitively, via the `Order` for declarations and notices) to `X-User-ID`. When `X-User-Role` is `CustomsOfficer`, `FinanceOfficer`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it on `AuditEvent` rows (as `actor_id`) but does not compare it to any entity's `id`.

The `Declarant` role drafts, submits, amends, and initiates refunds; it also creates orders on behalf of importers. The `CustomsOfficer` role is the privileged review and configuration role: it manages the HS code library, publishes tariff rules and exchange rates, registers importers and declarants, reviews declarations, issues queries, schedules inspections, approves or rejects declarations and refunds, grants conditional release, finalizes amendments, and operates the test-driving clock and event endpoints. The `FinanceOfficer` role confirms payments, reverses payments, and executes refund disbursements. The `Importer` role triggers order cancellation and return and reads its own orders, declarations, and payment notices. The `Auditor` role is read-only.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; the `offset` parameter defaults to 0. List responses default to sorting by `created_at` ascending. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix. Most resources also carry `created_at`, `updated_at`, and `version`. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `version` is an integer that begins at 1 on creation and is incremented by exactly 1 every time the resource is mutated, with `updated_at` refreshed in the same step. The `Order`, `Declaration`, `Query`, `PaymentNotice`, `Refund`, `Importer`, and `Declarant` entities carry the full set; the `HsCode`, `TariffRule`, `ExchangeRate`, `DeclarationLine`, `InspectionAppointment`, and `AuditEvent` entities carry only `id` and `created_at` — both `updated_at` and `version` are absent on those entities.

Mutating endpoints accept an optional `version` field in the request body. When present, the server compares it to the current resource version; if they do not match, the request is rejected with `ERR_INVALID_STATE_TRANSITION` and HTTP status 409. When the `version` field is omitted from the body, the optimistic concurrency check is skipped entirely.

### 2.5. Monetary Precision and Currency Handling

All monetary values are integer minor units. Order line amounts (`unit_price`, `total_value_minor`, `declared_value_minor`) are denominated in the order's `currency` ISO 4217 minor units (cents for USD, fen for CNY, and so on). Every value flowing through customs computation is converted into CNY fen at submission time and stored on the declaration as fields suffixed `_cny_minor` (`dutiable_value_cny_minor`, `tariff_amount_cny_minor`, `vat_amount_cny_minor`, `consumption_tax_cny_minor`, `total_tax_cny_minor`).

Rates are likewise integer-only. Tariff, VAT, consumption-tax, and postal-tax rates are stored as basis points where one basis point equals one one-hundredth of a percent — so a 5 percent rate is `500`, and a 13 percent rate is `1300`. Exchange rates are stored as integer micros where one rate-unit equals one million micros, so a USD-to-CNY rate of 7.123456 is stored as `rate_micros = 7123456`. Every multiplication that mixes minor units with rate basis points divides by 10,000 to recover minor units; every multiplication that mixes minor units with exchange-rate micros divides by 1,000,000. All such divisions truncate toward zero (a per-line floor is applied), and the order of operations is fixed: compute each line's contribution, floor that contribution, then sum across lines. Summing first and flooring the total is not equivalent and is not allowed.

### 2.6. Nested Resource Path Validation

Path segments that carry IDs are validated left-to-right. Given a request to a path such as the one identifying a particular `line_id` within a particular `declaration_id`, the server first verifies that the declaration exists; if it does not, the response is `ERR_NOT_FOUND` with HTTP status 404. Only after the declaration resolves does the server attempt to resolve the line, returning `ERR_NOT_FOUND` if the line is unknown. Single-segment ID parameters such as `query_id`, `refund_id`, `notice_id`, `appointment_id`, `hs_code_id`, `order_id`, and `importer_id` are resolved the same way — non-existence yields `ERR_NOT_FOUND`. Body-referenced foreign keys — `order_id` on declaration creation, `declaration_id` on refund creation, `hs_code_id` on line creation, and the body fields on inspection-appointment scheduling — are validated similarly with the same `ERR_NOT_FOUND` code.

### 2.7. State Cascades and Ledger-Style Audit

State changes propagate hierarchically. When a child declaration enters `APPROVED` or `CONDITIONALLY_RELEASED`, the parent order automatically advances from `PENDING_DECLARATION` to `DECLARED`; when the declaration subsequently enters `RELEASED`, the parent order advances from `DECLARED` to `RELEASED`. Each cascade increments the parent's `version` and refreshes its `updated_at`. State changes also generate immutable audit events: the system writes `AuditEvent` rows for declaration status changes, declaration field changes, tax recomputations, payment confirmations and reversals, refund decisions, and external-system synchronization pushes. Every audit event carries the `actor_role` and `actor_id` from the originating request, the `subject_type` (one of `DECLARATION`, `PAYMENT_NOTICE`, or `REFUND`), the `subject_id`, the `event_type`, and `before_value` and `after_value` JSON snapshots of the changed fields. Audit events are append-only; they are never updated or deleted, and the catalogue of `event_type` values is exactly `DECLARATION_FIELD_CHANGE`, `DECLARATION_STATUS_CHANGE`, `TAX_RECOMPUTED`, `PAYMENT_CONFIRMED`, `REFUND_DECISION`, and `EXTERNAL_SYNC`.

### 2.8. Idempotency for Payment Confirmation

Payment confirmation is the one mutating operation that requires an explicit idempotency contract. The caller must supply both an `Idempotency-Key` HTTP header and an `idempotency_key` field in the request body — when the header is missing, the request is rejected with `ERR_IDEMPOTENCY_KEY_REQUIRED` and HTTP status 400. The server stores the first successful (key, payload) pair against the notice; if a second request arrives with the same key and a payload that hashes identically, the server returns the stored prior result. If the second request arrives with the same key but a payload that hashes differently, the server rejects it with `ERR_IDEMPOTENCY_CONFLICT` and HTTP status 409.

### 2.9. Validation Priority

When multiple validations could apply to a single request, they are evaluated in a fixed order. Authentication runs first: the presence-and-non-empty check on `X-User-ID` and `X-User-Role` always precedes the role-permission check, so a missing header surfaces as the header error rather than as a forbidden-role error. Existence checks run next, with path-segment IDs validated left-to-right before body-referenced foreign keys. State-transition validity comes after existence; a transition request against a non-existent resource always surfaces as `ERR_NOT_FOUND` rather than as `ERR_INVALID_STATE_TRANSITION`. Business-referential checks (importer suspended, declaration uniqueness on an order) run after state validity. Business-constraint checks (template completeness, override status, rework limit, idempotency, channel-specific requirements, document completeness, HS code deprecation) and business-temporal checks (inspection slot overlap, payment notice expiry, tariff rule effective-window overlap) run last, in the priority order listed in the rules table. The contract-level consequence is that, in any race or layered failure, the response surfaces the highest-priority error rather than the most specific.

## 3. Business Logic & Workflows

### 3.1. Reference Data: HS Code Library, Tariff Rules, Exchange Rates, and Counterparties

A declaration is only as good as the reference data it cites, so the `CustomsOfficer` role bears responsibility for keeping that reference data correct. Each entry in the HS code library carries a 10-digit `code` that is unique across the library, a plain-language `description`, an array of lowercase `keywords` consumed by the classification suggestion engine, a `country_code_map` that maps an ISO-3166 alpha-2 destination country code to the local equivalent code (so a US destination might see `6109.10.0040` and an EU destination `61091000` for the same library entry), and four rate fields denominated in basis points: `tariff_rate_bps` (the default ad-valorem tariff), `vat_rate_bps` (the VAT rate applied to the dutiable value plus tariff plus consumption tax), `consumption_tax_rate_bps` (defaulting to zero for non-luxury goods), and `postal_tax_rate_bps` (the personal-postal-tax rate used for B2C direct mail). Every newly created HS code begins life with `status` set to `ACTIVE`. A customs officer may later deprecate a code; deprecation flips `status` to `DEPRECATED`, and from that moment forward the code may not be cited on a new line, though historical declarations that already reference it remain valid.

The default tariff rate on the HS code is the fallback. When a declaration submission needs to price a line, the server first looks for a `TariffRule` row whose `hs_code_id` matches the line's HS code, whose `origin_country` matches the declaration's origin (copied from the order), whose `destination_country` matches the declaration's destination, and whose `effective_from` is at or before the declaration's submission timestamp while `effective_to` is strictly after that timestamp (a null `effective_to` is treated as open-ended). When such a rule exists, its `tariff_rate_bps` overrides the HS code default; otherwise the HS code's own `tariff_rate_bps` applies. Tariff rules are open at the lower bound and closed at the upper bound, in the sense that the interval is `[effective_from, effective_to)`; the publishing endpoint guards against accidentally overlapping rules for the same triple of HS code, origin country, and destination country, rejecting any new rule whose interval overlaps an existing rule's interval with `ERR_TARIFF_RULE_OVERLAP`. Back-to-back rules where one's `effective_to` exactly equals the next's `effective_from` are explicitly allowed — that is a gap-free, overlap-free join, not an overlap.

Exchange rates are published as daily snapshots. Each `ExchangeRate` row pairs a `from_currency` and a `to_currency` (both ISO 4217), an integer `rate_micros`, and an `effective_date` formatted as a `YYYY-MM-DD` string. When a declaration is submitted, the server selects the exchange rate by finding, for the order's currency converted to CNY, the row whose `effective_date` is the latest one not after the submission date; that selected date is pinned onto the declaration as `exchange_rate_date_used` and the corresponding `rate_micros` is what the dutiable-value calculation uses. The pair `(from_currency, to_currency, effective_date)` is unique across the rate table.

Counterparties — the `Importer` and the `Declarant` — are also customs-officer-managed. An importer carries a legal `name`, a unique `license_number`, and a `status` that is `ACTIVE` by default; suspension is an explicit operator action that sets `status` to `SUSPENDED` and blocks creation or submission of declarations for that importer. A declarant carries a `name`, a unique customs-issued `agent_code`, and an analogous `status` that defaults to `ACTIVE` and is required to be `ACTIVE` at submission time.

### 3.2. Classification Suggestion: Picking Codes from a Product Description

A declarant who is unsure how to classify a line item asks the suggestion engine for help by submitting a `product_description` against the classification capability. The engine reads only the live HS code library — every row whose `status` is `ACTIVE` is a candidate, and `DEPRECATED` rows are ignored. For each candidate, the engine computes a `keyword_score` as the count of HS code keywords that appear as whole-word substrings in the lowercased product description, divided by the larger of one and the count of keywords on that HS code. It computes a `description_score` of one if the lowercased HS code description appears anywhere in the lowercased product description, and zero otherwise. The composite `score` is the keyword score multiplied by 0.7 plus the description score multiplied by 0.3, rounded half-up to six decimal places. The engine returns the top three candidates ranked by score descending, breaking ties by HS code ascending. If the highest score among any candidate is strictly less than 0.20, the engine returns an empty list, signaling that the description is too ambiguous and the declarant must classify manually. The pure-read suggestion endpoint writes nothing to the database and emits no audit event.

### 3.3. Order Intake and Drafting a Declaration

The lifecycle starts with an order. A declarant pushes an order — typically translating a merchant's ERP record — into the system by supplying an `external_order_ref` that is unique within the importer's namespace, the `importer_id` and `declarant_id`, the `trade_mode` (one of `B2C_DIRECT_MAIL`, `BONDED_WAREHOUSE`, or `GENERAL_TRADE`), the `origin_country` and `destination_country` as ISO-3166 alpha-2 codes, the order `currency`, an array of `line_items`, and a `total_value_minor` that equals the sum across line items of `quantity` multiplied by `unit_price`. Each entry of `line_items` carries `product_description`, `quantity`, `unit_price`, `weight_kg`, and an optional `hs_code_hint` — the description is what feeds back to the suggestion engine when a declarant decides to use it. Newly created orders begin in `PENDING_DECLARATION`.

An importer may step in at this stage with one of two terminal-leaning actions. Cancelling the order transitions it to `CANCELLED`; cancellation is allowed only when no declaration exists for the order, or when the only existing declaration is still in `DRAFT` (in which case the cancellation deletes that draft as a side effect). Marking the order as returned moves it to `RETURNED`; this is allowed when the order is currently in `DECLARED` or `RELEASED`, provided no `EXECUTED` `Refund` already exists against the declaration's payment notice. The `RETURNED` state is what unlocks a return-reason refund downstream.

When the declarant is ready to file with customs, they create a draft declaration against the order. The draft creation request supplies the `order_id`, the `dutiable_value_method` (one of `TRANSACTION_VALUE`, `DEDUCTIVE_VALUE`, or `COMPUTED_VALUE`), and — depending on the order's trade mode — one of three template-completion fields: `importer_id_card_number` for B2C direct mail, `bonded_zone_code` for the bonded warehouse mode, or `contract_number` for general trade. The server copies `declarant_id`, `trade_mode`, and `destination_country` from the parent order onto the new declaration, sets `submission_count` to zero, and places the declaration in `DRAFT`. At most one declaration may exist for a given order in a non-terminal state (terminal here means a declaration that has already been finalized as `REJECTED`, in the sense of being superseded); if a second declarant tries to create a parallel declaration on the same order, the second creation is rejected with `ERR_DECLARATION_ALREADY_EXISTS`. Two simultaneous creations against the same order serialize on this constraint with first-writer-wins semantics, and the second writer receives `ERR_DECLARATION_ALREADY_EXISTS` with HTTP status 409. If the importer was suspended at the moment of creation, the creation is rejected with `ERR_IMPORTER_SUSPENDED`.

### 3.4. Lines, Manual Override, and the Path to Submission

A declaration is decomposed into `DeclarationLine` rows that map the order's line items to specific HS codes. Each line carries an `order_line_index` that points back into `Order.line_items[]`, an `hs_code_id`, a `classification_source` recording how the code was chosen (one of `AUTO_SUGGESTED`, `MANUAL_OVERRIDE`, or `RULE_ENGINE`), and an `override_review_status` whose default is `NOT_APPLICABLE`. Lines are added one at a time via the line-creation capability while the parent declaration remains in `DRAFT`. The HS code referenced by `hs_code_id` must be in `ACTIVE` status at the moment of line creation; referencing a `DEPRECATED` code is rejected with `ERR_HS_CODE_DEPRECATED`. When the classification source on creation is `MANUAL_OVERRIDE`, the line's `override_review_status` is set to `PENDING` and a customs officer must subsequently approve or reject the override; for the other two sources, `override_review_status` remains `NOT_APPLICABLE`.

The override-review capability is exposed through a customs-officer action that supplies a `decision` of either `APPROVE` or `REJECT`. The override action is allowed only while the parent declaration is still in `DRAFT`; if the declaration has already moved past draft, the override action is rejected with `ERR_OVERRIDE_NOT_ALLOWED`. An approved override flips the line's `override_review_status` to `APPROVED`; a rejected override flips it to `REJECTED`.

Submission moves the declaration from `DRAFT` to `SUBMITTED` (and, on resubmission of a previously rejected declaration, from `REJECTED` to `SUBMITTED`). Submission is gated by the priority-ordered checks introduced in §2.9, so they fire in this order even when several would otherwise apply: existence and state validity first; then the importer must be `ACTIVE` (else `ERR_IMPORTER_SUSPENDED`) and the declarant must likewise be `ACTIVE`; then the per-trade-mode template-completeness check, which ensures the appropriate one of `importer_id_card_number`, `bonded_zone_code`, or `contract_number` was supplied (else `ERR_DECLARATION_INCOMPLETE`); then a check that no declaration line is in `PENDING` or `REJECTED` override status (else `ERR_LINES_HAVE_PENDING_OVERRIDE`); finally a check that `submission_count` is strictly less than 3 (else `ERR_REWORK_LIMIT_EXCEEDED`, which is the rejection-rework limit — after two rejections, a third resubmission attempt is refused). Submission is also the moment at which taxes are computed and audit events fire: the server increments `submission_count` by one, recomputes `tax_mode`, recomputes `dutiable_value_cny_minor` and `tariff_amount_cny_minor`, `vat_amount_cny_minor`, `consumption_tax_cny_minor`, and `total_tax_cny_minor`, pins `exchange_rate_date_used` to the latest available rate row whose effective date is at or before the submission date, and emits both a `DECLARATION_STATUS_CHANGE` and a `TAX_RECOMPUTED` audit event followed by an `EXTERNAL_SYNC` event simulating the push to the Customs Single Window. On resubmission after a rejection, the same recomputation runs and the existing `rejection_reason` is cleared.

### 3.5. The Dutiable Value Calculation in Three Variants

The dutiable value of a declaration is the per-line contributions summed; each line's contribution is computed in CNY fen per the declaration's chosen `dutiable_value_method`. The server resolves the line's order entry by `order_line_index` to recover the line's `quantity` and `unit_price`, then computes `line_value_minor` as the product `quantity * unit_price` in the order currency's minor units. Lines whose `override_review_status` is `REJECTED` would have already blocked submission and never reach this calculation.

Under `TRANSACTION_VALUE`, the line's CNY contribution is the simplest mapping: multiply `line_value_minor` by the pinned exchange rate's `rate_micros`, divide by 1,000,000, and floor toward zero. This yields the lowest of the three variants for a given line.

Under `DEDUCTIVE_VALUE`, the calculation begins from a presumed retail price equal to the transaction price multiplied by 125 and divided by 100 (i.e., a 25 percent retail markup), floored. From that presumed retail price, the calculation deducts a logistics-and-profit component computed by multiplying the retail price by `DEDUCTION_RATIO_BPS` and dividing by 10,000, where `DEDUCTION_RATIO_BPS` is fixed at 1500 (representing a 15 percent deduction); the deduction itself is floored. The deductive value is the retail price minus the deduction; the line's CNY contribution is the deductive value multiplied by the pinned `rate_micros` and divided by 1,000,000, again floored.

Under `COMPUTED_VALUE`, the calculation is cost-plus. First, a logistics component is computed by multiplying the line's `weight_kg` by `LOGISTICS_PER_KG_MINOR` (fixed at 5,000 fen, i.e., 50.00 CNY per kilogram) and rounding up to the next integer; the cost-plus base is `line_value_minor + logistics_minor`. The base is then uplifted by `COMPUTED_UPLIFT_BPS` (fixed at 1000, i.e., a 10 percent profit uplift) by multiplying it by 11,000, dividing by 10,000, and flooring. The line's CNY contribution is the uplifted value multiplied by the pinned `rate_micros` and divided by 1,000,000, floored.

Across all three variants, the order of operations is fixed: each line's contribution is computed and floored independently, and only then are the per-line contributions summed to produce `dutiable_value_cny_minor`. Computing the sum first and flooring the total would produce different values to the cent and is not equivalent.

### 3.6. Tax Composition: Standard Three-Tax vs. Personal Postal Tax

Once the dutiable value is known, the system decides the declaration's `tax_mode`. The mode is `PERSONAL_POSTAL` only when both conditions hold: the declaration's `trade_mode` is `B2C_DIRECT_MAIL`, and the declaration's `dutiable_value_cny_minor` is at most `PERSONAL_POSTAL_THRESHOLD_CNY_MINOR`, which is fixed at 500,000 fen (i.e., 5,000.00 CNY). The boundary is inclusive: a declaration whose dutiable value is exactly 5,000.00 CNY still qualifies for personal-postal mode if its trade mode is `B2C_DIRECT_MAIL`. In every other case (general trade, bonded warehouse, or B2C direct mail strictly above the threshold), the mode is `STANDARD`.

In `STANDARD` mode, the server walks the declaration's lines and computes three taxes per line. The line's tariff is `line_dutiable_value_cny_minor` multiplied by the applicable rate basis points (the per-(`hs_code_id`, `origin_country`, `destination_country`) `TariffRule.tariff_rate_bps` if a rule matches the submission timestamp's effective window per §3.1, otherwise the HS code's `tariff_rate_bps`), divided by 10,000, floored. The line's consumption tax is `line_dutiable_value_cny_minor` multiplied by the HS code's `consumption_tax_rate_bps`, divided by 10,000, floored. The VAT base for the line is the dutiable contribution plus the line tariff plus the line consumption tax — VAT compounds on top of the other two taxes — and the line VAT is that base multiplied by the HS code's `vat_rate_bps`, divided by 10,000, floored. The declaration's `tariff_amount_cny_minor`, `consumption_tax_cny_minor`, and `vat_amount_cny_minor` are the sums of the per-line floor results across all lines (floor per line, then sum); `total_tax_cny_minor` is their sum.

In `PERSONAL_POSTAL` mode, the three component taxes are zero. Per line, the postal tax is `line_dutiable_value_cny_minor` multiplied by the HS code's `postal_tax_rate_bps`, divided by 10,000, floored. The candidate total is the sum of per-line postal taxes; if that candidate total is at most `POSTAL_EXEMPTION_CNY_MINOR`, fixed at 5,000 fen (i.e., 50.00 CNY), the importer pays nothing and `total_tax_cny_minor` is set to zero — this is the statutory waiver for very small parcels. The exemption boundary is inclusive: a candidate total of exactly 50.00 CNY is exempt. If the candidate total exceeds the exemption, `total_tax_cny_minor` is the candidate total. In either personal-postal sub-case, `tariff_amount_cny_minor`, `vat_amount_cny_minor`, and `consumption_tax_cny_minor` remain zero.

### 3.7. Customs Review: Queries, Inspection, Approval, Rejection

Once a declaration is in `SUBMITTED`, a customs officer begins review by transitioning it from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW`, the officer has three forward paths: open a query and move the declaration into `QUERIED`; schedule an inspection and continue review; or finalize the review by approving or rejecting.

Queries are the supplementary-document loop. A customs officer asks a `question` and lists `required_documents` — an array of document type codes such as `INVOICE` or `COA` — as part of opening a query; this transitions the declaration from `UNDER_REVIEW` to `QUERIED` and pins `Declaration.query_id` to the new query, whose own `status` begins at `OPEN`. Opening a query is blocked when a `SCHEDULED` `InspectionAppointment` exists for the declaration (`ERR_INSPECTION_PENDING`). The declarant responds with `response_text` and `response_documents` (an array of `{doc_type, voucher_url}` entries); the response is rejected with `ERR_QUERY_DOCUMENTS_INCOMPLETE` if any `doc_type` listed in `required_documents` lacks a matching entry in `response_documents`. The match is exact and case-sensitive on `doc_type`; an empty `required_documents` list trivially passes. A successful response moves the query to `RESPONDED`. The customs officer then resolves the query, which moves the query to `RESOLVED`, clears `Declaration.query_id`, and returns the declaration from `QUERIED` to `UNDER_REVIEW`.

Inspections are scheduled appointments at a single inspection bay. Each `InspectionAppointment` is a 60-minute exclusive interval pinning a `bay_code` and a `scheduled_at` start instant. New appointments are checked against existing `SCHEDULED` appointments on the same `bay_code`: a new `scheduled_at` may not fall in the half-open 60-minute window starting at any existing appointment's start, and no existing appointment's start may fall in the new appointment's half-open 60-minute window. Stated equivalently, two appointments on the same `bay_code` are in conflict whenever their intervals `[scheduled_at, scheduled_at + 60min)` overlap. A conflict is reported as `ERR_INSPECTION_SLOT_TAKEN`. Two clients racing to schedule the same overlapping slot serialize first-writer-wins on the bay-and-time pair, with the loser receiving `ERR_INSPECTION_SLOT_TAKEN`. Once scheduled, an appointment may be either `COMPLETED` or `CANCELLED` by a customs officer, and any `SCHEDULED` appointment must reach `COMPLETED` before the declaration can be approved.

Approval is the customs officer's final positive verdict. An approval request is rejected with `ERR_INVALID_STATE_TRANSITION` if there is still an open query (i.e., `Declaration.query_id` is non-null), and with `ERR_INSPECTION_PENDING` if any `SCHEDULED` `InspectionAppointment` for the declaration has not yet been completed. A clean approval transitions the declaration from `UNDER_REVIEW` to `APPROVED`, which fires three effects: the system creates a `PaymentNotice` whose `amount_cny_minor` equals the declaration's current `total_tax_cny_minor` (an immutable snapshot taken at approval time) and whose `due_at` is set to 168 hours after creation, the parent order cascades from `PENDING_DECLARATION` to `DECLARED`, and a `DECLARATION_STATUS_CHANGE` audit event is emitted.

Rejection sends the declaration from `UNDER_REVIEW` to `REJECTED`, persisting the customs officer's `rejection_reason` and emitting a `DECLARATION_STATUS_CHANGE` audit event. A declaration in `REJECTED` is not a dead end: the declarant may resubmit, in which case all submission preconditions re-apply and `submission_count` increments (capped strictly below 3 — the third resubmission attempt fails with `ERR_REWORK_LIMIT_EXCEEDED`). When a declaration is in `UNDER_REVIEW`, two simultaneous mutating actions — for example, a customs officer rejecting at the same instant that the declarant tries to issue an amendment — serialize first-writer-wins on the declaration's status, with the loser receiving `ERR_INVALID_STATE_TRANSITION`.

### 3.8. Payment, Conditional Release, and the Path to RELEASED

The payment notice is the bridge between approval and release. Each `PaymentNotice` is created automatically on declaration approval and carries the immutable `amount_cny_minor` snapshot, the `due_at` (168 hours after creation), and a `status` that starts at `PENDING`. The notice supports three payment channels: `BANK_TRANSFER`, `ELECTRONIC_PAYMENT`, and `GUARANTEE_DEDUCTION`. The selected `payment_channel` is pinned at confirmation time, not at notice creation. A bank-transfer confirmation requires a non-empty `voucher_url`; without it the request is rejected with `ERR_VOUCHER_REQUIRED`. A guarantee-deduction confirmation requires that the linked declaration be in `APPROVED` or `CONDITIONALLY_RELEASED`. Every confirmation request must also carry the `Idempotency-Key` header described in §2.8 along with the matching `idempotency_key` body field.

A confirmation that arrives after the notice's `due_at` is rejected with `ERR_PAYMENT_NOTICE_EXPIRED`; the comparison is against the current clock at request time, with `due_at` exclusive — that is, a notice at exactly `due_at` is already expired. The system also auto-expires `PENDING` notices when the clock advances past their `due_at`: every time the test-driving clock-advance capability moves the system clock forward, any notice whose `due_at` has now passed transitions from `PENDING` to `EXPIRED`.

A successful confirmation flips the notice from `PENDING` to `PAID`, cascades the linked declaration from `APPROVED` to `RELEASED` (or from `CONDITIONALLY_RELEASED` to `RELEASED`, as the case may be), and emits both a `PAYMENT_CONFIRMED` audit event and an `EXTERNAL_SYNC` audit event simulating the push from the payment gateway. The declaration's transition to `RELEASED` cascades again to the parent order, advancing it from `DECLARED` to `RELEASED`, and pins `pickup_coordinated_at` on the declaration to the current clock; an `EXTERNAL_SYNC` audit event is emitted simulating the logistics-system pickup-coordination push.

Conditional release is a parallel path available only when the payment channel is `GUARANTEE_DEDUCTION`. A customs officer transitions the declaration from `APPROVED` to `CONDITIONALLY_RELEASED`, which sets `release_condition` to `'guarantee_deposit_required'` and cascades the parent order from `PENDING_DECLARATION` to `DECLARED` if it is not already there. An attempt to grant conditional release while the payment channel is anything other than `GUARANTEE_DEDUCTION` is rejected with `ERR_CHANNEL_NOT_GUARANTEE`. Once the guarantee is later confirmed (the same payment confirmation flow), the declaration moves from `CONDITIONALLY_RELEASED` to `RELEASED`, `release_condition` is cleared, the parent order cascades from `DECLARED` to `RELEASED`, and the same logistics-coordination effects fire.

A confirmed payment may be reversed by a finance operator. The reversal request supplies a `reverse_reason`. Reversal is forbidden when an `EXECUTED` `Refund` already exists against the declaration, in which case the reversal is rejected with `ERR_REFUND_ALREADY_EXECUTED`. A successful reversal flips the notice from `PAID` to `REVERSED`; if the linked declaration was in `RELEASED`, it reverts to `APPROVED` (the order's `RELEASED` cascade is similarly undone). A `PAYMENT_CONFIRMED` audit event with the reverse marker is emitted. Operations downstream of a reversed payment are blocked with `ERR_PAYMENT_REVERSED` — including a refund approval that arrives just after a reverse race wins; two concurrent attempts (a reverse and a refund approval) serialize first-writer-wins on the notice's status, and the refund-approval loser receives `ERR_PAYMENT_REVERSED`.

### 3.9. Post-Release Amendment

Released declarations are not frozen. A declarant may file a post-release amendment as long as the linked `PaymentNotice` is in `PAID` and no `EXECUTED` `Refund` exists for the declaration. The amendment request supplies a `lines` array of line edits — each entry carries a `line_id` and optionally a new `hs_code_id` and/or a new `dutiable_value_method` — and transitions the declaration from `RELEASED` to `AMENDED`. The transition recomputes `dutiable_value_cny_minor` and the full tax composition under the new line classifications, and emits both a `DECLARATION_FIELD_CHANGE` and a `TAX_RECOMPUTED` audit event. If the recomputed `total_tax_cny_minor` differs from the immutable snapshot held by the `PaymentNotice.amount_cny_minor`, the system records the difference for audit. A customs officer subsequently finalizes the amendment, transitioning it from `AMENDED` back to `RELEASED` and emitting a `DECLARATION_STATUS_CHANGE` audit event.

### 3.10. Refunds: Three Reasons, Two Calculation Variants

Refunds pull money back through the same financial pipe, but the eligibility rules and amount calculations split by `refund_reason`. The supported reasons are `RETURN`, `ORDER_CANCELLATION`, and `ERRONEOUS_DECLARATION`.

A refund draft is created against a `declaration_id` along with the `refund_reason` and an array of `supporting_documents` (each entry of the form `{doc_type, voucher_url}`). The draft is then submitted, which is where the refund-eligibility checks fire and the refundable amount is computed.

For submission to succeed, the linked declaration must be in `RELEASED` or `AMENDED`, and the linked payment notice must be in `PAID`. The cross-entity guard then matches the refund reason to the order's status: a `RETURN` refund requires the parent order to be in `RETURNED`, and an `ORDER_CANCELLATION` refund requires the parent order to be in `CANCELLED`; an `ERRONEOUS_DECLARATION` refund does not impose an order-status condition. A mismatch on the cross-entity guard yields `ERR_ORDER_NOT_ELIGIBLE`. The supporting-documents check is reason-specific: a `RETURN` refund must include a document of type `SHIPMENT_RETURN_RECEIPT`, an `ORDER_CANCELLATION` refund must include `CANCELLATION_AGREEMENT`, and an `ERRONEOUS_DECLARATION` refund must include `AMENDMENT_DECISION`; missing the required type yields `ERR_REFUND_DOCUMENTS_INCOMPLETE`. For `ERRONEOUS_DECLARATION` refunds only, an additional fiscal eligibility check fires: the post-amendment `Declaration.total_tax_cny_minor` must be strictly less than `PaymentNotice.amount_cny_minor` (the original snapshot); when the amendment raised the tax instead of lowering it — that is, when the post-amendment total is at or above the snapshot — the refund is rejected at this guard with `ERR_REFUND_NOT_ELIGIBLE`, before the amount calculation runs.

The refund amount is computed against the payment notice's snapshot. For `RETURN` refunds, the refundable amount is the entire `PaymentNotice.amount_cny_minor` — the goods never effectively cleared, so the full tax is returned. For `ORDER_CANCELLATION` refunds, the refundable amount is likewise the entire `PaymentNotice.amount_cny_minor` — the cancellation rolls back a conditional release. For `ERRONEOUS_DECLARATION` refunds, the refundable amount is the larger of zero and the difference between `PaymentNotice.amount_cny_minor` and the current `Declaration.total_tax_cny_minor`; the maximum-against-zero is a defensive guard that prevents a negative refund from ever being persisted, even though the eligibility guard upstream should already have rejected such cases. At most one `EXECUTED` refund may exist per declaration. A successful submission emits a `REFUND_DECISION` audit event marked submitted, and pins `refundable_amount_cny_minor` on the refund.

A submitted refund is decided by a customs officer — approval transitions it from `SUBMITTED` to `APPROVED` and emits a `REFUND_DECISION` event marked approved; rejection transitions it from `SUBMITTED` to `REJECTED`, persists the customs officer's `rejection_reason`, and emits a `REFUND_DECISION` event marked rejected. Approved refunds are then disbursed by a finance operator, transitioning from `APPROVED` to `EXECUTED`; on execution, `executed_amount_cny_minor` is set equal to `refundable_amount_cny_minor`, a `REFUND_DECISION` event marked executed is emitted, and an `EXTERNAL_SYNC` event simulating the ERP refund posting is emitted.

### 3.11. Audit Trail, Test-Driving the Clock, and External Synchronization

Every state-machine transition described in this section emits at least one audit event, and customs operators routinely query the audit log to reconstruct what happened. A `subject_type?`, `subject_id?`, or `event_type?` filter narrows the listing; the audit-event listing also accepts `limit?` and `offset?` for pagination per §2.3.

Two operator capabilities exist purely to drive deterministic tests. The clock-advance capability is restricted to the `CustomsOfficer` role and accepts a number of `seconds` to move the system clock forward; advancing the clock past one or more `due_at` values causes the system to re-evaluate every `PENDING` `PaymentNotice` and transition any whose `due_at` has been crossed from `PENDING` to `EXPIRED`. The synthetic-event capability is also `CustomsOfficer`-only and lets a test simulate one of four counterparty pushes — `'CUSTOMS_SINGLE_WINDOW_ACK'`, `'PAYMENT_GATEWAY_PUSH'`, `'LOGISTICS_PICKUP_ACK'`, or `'ERP_ORDER_UPDATE'` — against a given `subject_id`, emitting a corresponding `EXTERNAL_SYNC` audit event that downstream tests can verify.

## 4. Endpoint Definitions

The endpoints below are defined relative to the API root. Successful resource creation returns HTTP 201 with the new resource in the response envelope's `data` field; successful modifications, including state transitions and reads, return HTTP 200. Request bodies, response payloads, and side effects are described in the §3 narratives — this table lists only the contract-level method, path, intent, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /hs_codes | Create an HS code library entry | CustomsOfficer |
| POST | /hs_codes/{hs_code_id}/deprecate | Deprecate an HS code | CustomsOfficer |
| GET | /hs_codes/{hs_code_id} | Fetch an HS code | CustomsOfficer, Declarant, Auditor |
| POST | /classification/suggest | Suggest HS codes for a product description | Declarant |
| POST | /tariff_rules | Publish a tariff rule (origin-specific override) | CustomsOfficer |
| POST | /exchange_rates | Publish a daily exchange rate | CustomsOfficer |
| POST | /importers | Create an importer | CustomsOfficer |
| POST | /importers/{importer_id}/suspend | Suspend an importer | CustomsOfficer |
| POST | /declarants | Create a declarant | CustomsOfficer |
| POST | /orders | Create an order | Declarant |
| POST | /orders/{order_id}/cancel | Cancel an order | Importer |
| POST | /orders/{order_id}/return | Mark an order returned | Importer |
| GET | /orders/{order_id} | Fetch an order | Declarant, CustomsOfficer, Importer, Auditor |
| POST | /declarations | Create a draft declaration | Declarant |
| POST | /declarations/{declaration_id}/lines | Add a declaration line | Declarant |
| POST | /declarations/{declaration_id}/lines/{line_id}/override | Approve or reject a manual classification override | CustomsOfficer |
| POST | /declarations/{declaration_id}/submit | Submit (or resubmit) a declaration | Declarant |
| POST | /declarations/{declaration_id}/start_review | Begin customs review | CustomsOfficer |
| POST | /declarations/{declaration_id}/queries | Open a supplementary-document query | CustomsOfficer |
| POST | /queries/{query_id}/respond | Respond to a query | Declarant |
| POST | /queries/{query_id}/resolve | Resolve a query | CustomsOfficer |
| POST | /declarations/{declaration_id}/inspection_appointments | Schedule an inspection | CustomsOfficer |
| POST | /inspection_appointments/{appointment_id}/complete | Complete an inspection | CustomsOfficer |
| POST | /inspection_appointments/{appointment_id}/cancel | Cancel an inspection | CustomsOfficer |
| POST | /declarations/{declaration_id}/reject | Reject a declaration | CustomsOfficer |
| POST | /declarations/{declaration_id}/approve | Approve a declaration and auto-generate a payment notice | CustomsOfficer |
| POST | /declarations/{declaration_id}/conditional_release | Grant conditional release | CustomsOfficer |
| POST | /declarations/{declaration_id}/amend | File a post-release amendment | Declarant |
| POST | /declarations/{declaration_id}/finalize_amendment | Finalize an amendment | CustomsOfficer |
| GET | /declarations/{declaration_id} | Fetch a declaration with derived fields | Declarant, CustomsOfficer, Importer, Auditor |
| GET | /declarations | List declarations with filters | Declarant, CustomsOfficer, Auditor |
| GET | /payment_notices/{notice_id} | Fetch a payment notice | Declarant, FinanceOfficer, Importer, Auditor |
| POST | /payment_notices/{notice_id}/confirm_payment | Confirm payment via channel (idempotent) | FinanceOfficer |
| POST | /payment_notices/{notice_id}/reverse | Reverse a confirmed payment | FinanceOfficer |
| POST | /refunds | Create a draft refund | Declarant |
| POST | /refunds/{refund_id}/submit | Submit a refund | Declarant |
| POST | /refunds/{refund_id}/approve | Approve a refund | CustomsOfficer |
| POST | /refunds/{refund_id}/reject | Reject a refund | CustomsOfficer |
| POST | /refunds/{refund_id}/execute | Disburse an approved refund | FinanceOfficer |
| GET | /refunds/{refund_id} | Fetch a refund | Declarant, CustomsOfficer, FinanceOfficer, Auditor |
| GET | /audit_events | List audit events with filters | Auditor, CustomsOfficer |
| POST | /_clock/advance | Advance the system clock (test-driving) | CustomsOfficer |
| POST | /_events/emit | Emit a synthetic external-system event (test-driving) | CustomsOfficer |

## 5. Error Code Catalogue

The conditions under which each error fires are scattered through §2 and §3; this table exists to fix the wire-level identifier and HTTP status for each error.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_DECLARATION_ALREADY_EXISTS | 409 |
| ERR_DECLARATION_INCOMPLETE | 422 |
| ERR_LINES_HAVE_PENDING_OVERRIDE | 409 |
| ERR_REWORK_LIMIT_EXCEEDED | 409 |
| ERR_HS_CODE_DEPRECATED | 409 |
| ERR_OVERRIDE_NOT_ALLOWED | 409 |
| ERR_IMPORTER_SUSPENDED | 409 |
| ERR_INSPECTION_PENDING | 409 |
| ERR_INSPECTION_SLOT_TAKEN | 409 |
| ERR_QUERY_DOCUMENTS_INCOMPLETE | 422 |
| ERR_PAYMENT_NOTICE_EXPIRED | 409 |
| ERR_VOUCHER_REQUIRED | 422 |
| ERR_IDEMPOTENCY_KEY_REQUIRED | 400 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_CHANNEL_NOT_GUARANTEE | 409 |
| ERR_PAYMENT_REVERSED | 409 |
| ERR_REFUND_DOCUMENTS_INCOMPLETE | 422 |
| ERR_REFUND_NOT_ELIGIBLE | 409 |
| ERR_REFUND_ALREADY_EXECUTED | 409 |
| ERR_ORDER_NOT_ELIGIBLE | 409 |
| ERR_TARIFF_RULE_OVERLAP | 409 |
