# SaaS Subscription Billing API — Product Requirements Document

## 1. Introduction

A multi-tenant SaaS platform earns its revenue through subscriptions, and the integrity of that revenue depends on a billing surface that can reason simultaneously about *people* (tenants), *products* (packages), *consumption* (usage), and *money* (invoices, payments, credit notes). This document defines the REST API that platform operators, finance teams, and tenant administrators use to provision tenants, sell them packages, meter their consumption, bill them, collect from them, and — when payments stall — escalate them through a dunning lifecycle that culminates in suspension or termination.

The system serves three distinct constituencies with very different blast radii. A `PlatformAdmin` configures the commercial catalog and arbitrates lifecycle events across every tenant. A `BillingOperator` reviews and adjusts invoices, issues credits, and posts payments without ever creating or destroying a tenant. A `TenantAdmin` operates within the boundary of a single tenant: starting a trial, picking a plan, recording usage, paying invoices, and (after a payment recovers a suspended account) regaining full access. Across all three, every monetary computation is deterministic and every state transition is fully observable through an append-only audit log and an outbound event stream that synchronizes with downstream payment, accounting, CRM, and tax-compliance systems.

The design pressure points are predictable and addressed deliberately: idempotent usage and payment ingestion under retries; pro-rated mid-cycle plan changes that must reconcile cleanly with the next invoice; tiered overdue handling that progressively restricts the tenant before suspending the account; tax computation that respects each jurisdiction's rounding doctrine; and concurrent plan-change races that must serialize to exactly one winner.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller. The `X-User-Role` header declares which role the request is acting under, and must be one of `PlatformAdmin`, `BillingOperator`, or `TenantAdmin` — any other value, or a missing header, is rejected with `ERR_AUTH_MISSING_ROLE` (HTTP 401). The `X-User-ID` header identifies the specific principal acting under that role and is likewise mandatory; absence yields `ERR_AUTH_MISSING_USER` (HTTP 401). When both headers are present but the declared role is not permitted to invoke the requested endpoint per the RBAC matrix in §4, the system rejects with `ERR_FORBIDDEN` (HTTP 403).

The semantics of `X-User-ID` depend on the role. When `X-User-Role` is `PlatformAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on resulting `AuditLog` entries (as `actor_id`) and on the outbound event log but does not compare it against any entity's `id`. The same holds when `X-User-Role` is `BillingOperator` — opaque operator identifier, recorded as `actor_id` on audit entries, never compared. When `X-User-Role` is `TenantAdmin`, however, `X-User-ID` is the `id` of the acting `Tenant`; ownership checks on any tenant-scoped resource compare the path's `tenant_id` to `X-User-ID`, and a mismatch yields `ERR_CROSS_TENANT_ACCESS` (HTTP 403). A `TenantAdmin` therefore cannot read or mutate any tenant other than its own, regardless of any other authorization rule.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and may not exceed 100; the `offset` parameter defaults to 0 and has no upper bound. All list endpoints sort results by `created_at` ascending. The response `meta` block on every list endpoint reports `limit`, `offset`, `total_count` (the total number of resources matching the query), and `has_more` (true when more resources exist beyond the returned window).

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` formatted as a UUID with no type prefix and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Resources that represent ongoing state — `Tenant`, `Subscription`, `Invoice` — additionally expose an `updated_at` timestamp (refreshed on every mutation) and a monotonically increasing integer `version` (initialized at 1 on creation, incremented by exactly 1 on every mutation). Resources that are immutable by construction — `PackageVersion` (a frozen configuration snapshot), `SubscriptionChange` (an event log entry), `UsageRecord` (append-only metering), `Payment` (a recorded receipt), `CreditNote` (an issued credit), `Jurisdiction` (a configuration record), `SyncEvent` (an outbound event), and `AuditLog` (an audit entry) — carry only `id` and `created_at`; both `updated_at` and `version` are absent on these entities.

### 2.5. Optimistic Concurrency Control

For mutable resources, mutating endpoints accept an optional `version` field in their request body or query parameters. When supplied, it is compared against the server's currently stored `version`; a mismatch is rejected with `ERR_VERSION_CONFLICT` (HTTP 409). Clients that omit the `version` field skip this check and accept last-writer semantics — the mutation proceeds regardless of intervening writes. On a successful mutation, `version` is incremented by 1 and `updated_at` is refreshed to the request's processing timestamp.

### 2.6. Multi-Tenancy Isolation and Hierarchical Billing Entities

Every tenant-scoped resource (subscriptions, invoices, usage records, payments, credit notes, sync events, audit logs) carries a `tenant_id` that ties it to exactly one `Tenant`. A `TenantAdmin` whose `X-User-ID` does not equal the path's `tenant_id` is rejected with `ERR_CROSS_TENANT_ACCESS` regardless of which downstream resource is targeted.

Tenants themselves declare a `billing_entity_type` of `INDEPENDENT`, `PARENT`, or `SUBSIDIARY`. When `billing_entity_type` is `SUBSIDIARY`, the tenant must reference an existing parent via `parent_tenant_id`; the referenced tenant must itself have `billing_entity_type` of `PARENT`, or the create request is rejected with `ERR_INVALID_PARENT_TENANT` (HTTP 422). For `INDEPENDENT` and `PARENT` tenants, `parent_tenant_id` is null. Subsidiaries maintain their own outstanding balances; a parent does *not* automatically absorb subsidiary balances into its own `outstanding_balance_cents`, and the two records remain independent for billing purposes.

### 2.7. Nested Resource Resolution

Routes that nest resources under a parent (for example, the subscriptions, invoices, usage records, payments, credit notes, sync-event, and audit-log routes under a tenant) validate path parameters left-to-right. The tenant referenced by `tenant_id` is resolved first; a missing tenant yields `ERR_TENANT_NOT_FOUND` (HTTP 404). Only then is the inner resource resolved: a missing or cross-tenant subscription yields `ERR_SUBSCRIPTION_NOT_FOUND`, a missing or cross-tenant invoice yields `ERR_INVOICE_NOT_FOUND`. The inner resource must belong to the path tenant — a subscription whose `tenant_id` does not equal the path's `tenant_id` is treated as not-found, never as forbidden. References to a `PackageVersion` that cannot be resolved for the given `package_code` at the relevant timestamp yield `ERR_PACKAGE_NOT_FOUND`; references to a tax jurisdiction whose `jurisdiction_code` is not registered yield `ERR_JURISDICTION_NOT_FOUND`.

### 2.8. Monetary Precision, Currency, and Tax Rounding

All monetary fields across the system are stored as signed integer cents, and intermediate sums in any billing computation remain in integer cents throughout. The final rounding step on tax computation and on late-fee computation uses **round half up** to the nearest cent. The only places rounding is performed are: (a) tax computation per the jurisdiction's `rounding_mode`, (b) late-fee accrual on each ISSUED, PARTIALLY_PAID, or OVERDUE invoice, and (c) the final proration result, which is rounded to integer cents only at the very last step. Every currency code is an ISO 4217 three-letter code such as `USD`, `EUR`, `GBP`, or `JPY`. A `Subscription` is valid only when the resolved `PackageVersion.currency` equals the owning `Tenant.currency`; mismatch is rejected with `ERR_CURRENCY_MISMATCH`. A `Payment.currency` must equal the targeted `Invoice.currency` or it is likewise rejected with `ERR_CURRENCY_MISMATCH`.

### 2.9. Hierarchical Consistency, Cascades, and Event Emission

Whenever a transition mutates more than one entity, the dependent updates are part of the same atomic step. A subscription upgrade replaces the subscription's `package_version_id`, resets `quota_consumed` to an empty map, creates an immutable `SubscriptionChange` entry, issues a prorated `Invoice`, refreshes `updated_at`, increments `version`, emits an outbound `SyncEvent`, and writes a corresponding `AuditLog` entry — all in one logical operation. A payment that clears the last outstanding invoice cascades to reset the subscription's `payment_status` to `CURRENT`, clear the tenant's `restriction_level` to `NONE`, and (when applicable) lift the tenant's `tenant_status` from `SUSPENDED` back to `ACTIVE`. The cascades, the `updated_at`/`version` bookkeeping, the SyncEvent emission, and the AuditLog write are all specified per transition in §3.

### 2.10. Idempotency and Concurrency Serialization

The system serializes contended writes against named uniqueness constraints. Two concurrent upgrade requests on the same subscription serialize on the subscription's `version`; one succeeds and the other receives `ERR_SUBSCRIPTION_CHANGE_IN_FLIGHT` (HTTP 409). The same rejection applies when an upgrade and a downgrade race on the same subscription. Two payments submitted simultaneously with the same `external_reference` for the same tenant serialize on the composite `(tenant_id, external_reference)` uniqueness key; exactly one Payment is persisted, and an identical replay returns the originally persisted Payment with HTTP 201 (pure idempotent replay). A conflicting body that reuses the same key with different details is rejected with `ERR_DUPLICATE_PAYMENT_REFERENCE`. The same pattern governs usage ingestion: two concurrent submissions sharing `(subscription_id, idempotency_key)` produce exactly one `UsageRecord`; identical replay returns the original record at 201, while conflicting replay yields `ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY`. Invoice issuance is similarly serialized — only one Invoice per `(subscription_id, cycle_start, pricing_model)` may exist, and a racing issuance attempt yields `ERR_INVOICE_CYCLE_ALREADY_ISSUED`. Package definitions are serialized on `(package_code, version_number)` uniqueness with `ERR_PACKAGE_VERSION_DUPLICATE` as the loser's response.

### 2.11. Validation Priority

When a request would fail multiple validations simultaneously, validations are evaluated in this strict order, and the first failing check determines the rejection error:

1. Authentication: `X-User-Role` presence and recognized value (`ERR_AUTH_MISSING_ROLE`), then `X-User-ID` presence (`ERR_AUTH_MISSING_USER`).
2. Authorization: the role is permitted to call the endpoint per §4's RBAC matrix (`ERR_FORBIDDEN`).
3. Existence, left-to-right: tenant, then nested resource (subscription, invoice), then referenced package or jurisdiction.
4. Multi-tenancy isolation: a `TenantAdmin` whose `X-User-ID` does not match the path's `tenant_id` is rejected at `ERR_CROSS_TENANT_ACCESS` before any state or business check fires.
5. State preconditions: tenant status, then subscription status, then invoice status must each be in the set declared for the operation; otherwise `ERR_TENANT_STATUS_INVALID`, `ERR_SUBSCRIPTION_STATUS_INVALID`, or `ERR_INVOICE_STATUS_INVALID`.
6. Restriction gating during dunning: `ERR_TENANT_READ_ONLY` and `ERR_TENANT_FEATURE_RESTRICTED` (see §2.12).
7. Optimistic concurrency: when supplied, `version` must match the stored value (`ERR_VERSION_CONFLICT`); then no other plan-change must be in flight on the same subscription (`ERR_SUBSCRIPTION_CHANGE_IN_FLIGHT`).
8. Business referential integrity: parent-tenant validity, currency match between package and tenant or payment and invoice.
9. Business temporal: upgrade-direction, downgrade-direction, usage timestamp within the late-arrival window.
10. Business constraint and fiscal: uniqueness keys, positive amounts, non-negative quantities, discount range, outstanding balance, attached subsidiaries.

The compliance, isolation, state, and OCC checks therefore always run before the financial and uniqueness checks; a stale `version` is reported as `ERR_VERSION_CONFLICT` rather than being masked by a later business rejection.

### 2.12. Restriction Gating During Dunning

While a tenant's `tenant_status` is `ACTIVE` and its `restriction_level` is `READ_ONLY` or `FEATURE_RESTRICTED`, the system blocks most mutations. Specifically, all POST, PATCH, and DELETE requests scoped to the tenant — *except* the payment endpoint, which must always remain available so the tenant can clear its debt — are rejected with `ERR_TENANT_READ_ONLY` while `restriction_level` is either `READ_ONLY` or `FEATURE_RESTRICTED`. Read endpoints are unaffected. Additionally, when `restriction_level` is `FEATURE_RESTRICTED`, attempts to ingest a `UsageRecord` whose `metric` is `API_CALL` and whose ingestion would push `quota_consumed['api_calls']` beyond the resolved `PackageVersion.included_quotas['api_calls']` are rejected with `ERR_TENANT_FEATURE_RESTRICTED`.

### 2.13. Audit and Event Synchronization

Every mutation that alters tenant lifecycle, subscription lifecycle, or financial state writes an `AuditLog` entry capturing the `tenant_id`, the request's `actor_role`, the request's `actor_id`, the `action`, the `target_entity_type` and `target_entity_id`, and JSON `before_snapshot` and `after_snapshot` blocks. Similarly, lifecycle transitions emit `SyncEvent` rows tagged with a `target_system` of `PAYMENT_PAY`, `ACCOUNTING`, `CRM`, or `TAX_COMPLIANCE`, an `event_type` drawn from `SUBSCRIPTION_CREATED`, `SUBSCRIPTION_CHANGED`, `INVOICE_ISSUED`, `PAYMENT_RECEIVED`, `TENANT_SUSPENDED`, or `TENANT_REACTIVATED`, a frozen JSON `payload` snapshot of the affected entity, and a `delivery_status` that begins at `QUEUED` and transitions to `DELIVERED` once the system has handed the event off. `FAILED` is reserved for downstream test triggers; this system does not produce it.

## 3. Business Logic & Workflows

### 3.1. Packages, Versions, and the Pricing Catalog

Before any tenant can subscribe, a `PlatformAdmin` populates the catalog of available offerings. A package is identified across versions by a stable `package_code` such as `"STARTER"`; each new revision of a package is a `PackageVersion` with a strictly monotonic `version_number` starting at 1, and the pair `(package_code, version_number)` is globally unique — a duplicate yields `ERR_PACKAGE_VERSION_DUPLICATE`. Every version declares a `package_type` of `TIERED`, `USAGE_BASED`, or `HYBRID`, an `effective_from` ISO 8601 UTC timestamp marking when this version becomes the catalog representative for that package code, a `currency` ISO 4217 code, a `billing_cycle` of `MONTHLY`, `QUARTERLY`, or `ANNUAL`, and a `pricing_model` of `PREPAID` or `POSTPAID`. A `HYBRID` package is always treated as `PREPAID` for its base charge and `POSTPAID` for any overage charge, regardless of the literal `pricing_model` value.

The `base_price_cents` is the recurring price charged once per billing cycle. For a `USAGE_BASED` package, this value is 0; everything the tenant pays comes from metered overage. The `included_quotas` field is a map from metric name (`seats`, `api_calls`, `storage_gb`, `bandwidth_gb`, `active_users`) to an integer cap; a metric absent from the map means zero is included. The `tiered_brackets` field is an ordered list of `{metric, upper_bound, unit_price_cents}` entries used for `TIERED` and `HYBRID` packages; the last bracket in the list per metric has its `upper_bound` set to null to mean "no upper limit"; the field is empty for `USAGE_BASED` packages. The `overage_rates` field is a per-metric flat rate in cents per unit used when no tier bracket applies, populated for `USAGE_BASED` and `HYBRID` packages and empty for `TIERED`. The `addons` field lists optional purchases each with a code and a `monthly_price_cents`.

When a subscription resolves a package, the system selects the `PackageVersion` with the largest `effective_from` less than or equal to the request's timestamp for that `package_code` — i.e., the most recent version that has already taken effect. A subscription locks this resolved version into its `package_version_id` at activation and at every upgrade or immediate-refund downgrade.

`PackageVersion` is immutable once created; its resource representation carries only `id`, `created_at`, and the fields above — no `updated_at`, no `version`.

### 3.2. Tenant Onboarding, Trial, and Termination

A `PlatformAdmin` creates a new tenant by supplying its `legal_name`, primary `contact_email` and `contact_phone`, a `billing_entity_type`, optionally a `parent_tenant_id` when the entity type is `SUBSIDIARY`, an ISO 4217 `currency`, the `jurisdiction_code` of an existing `Jurisdiction`, and optionally a `trial_expires_at` deadline. The new tenant starts in `tenant_status` of `TRIAL` with `restriction_level` of `NONE`. The system records the creation in the audit log and emits a placeholder `SyncEvent` to `CRM` so the downstream CRM has a record of the new account from the moment of creation, before any subscription has been provisioned. If `billing_entity_type` is `SUBSIDIARY` and the supplied `parent_tenant_id` is missing or refers to a tenant whose own `billing_entity_type` is not `PARENT`, the create attempt is rejected with `ERR_INVALID_PARENT_TENANT`. If the supplied `jurisdiction_code` is not registered in the catalog, the attempt is rejected with `ERR_JURISDICTION_NOT_FOUND`.

A tenant remains in `TRIAL` until one of three things happens. First, the `TenantAdmin` (or a `PlatformAdmin` acting on their behalf) can convert a `TRIAL` subscription to a paid one via trial-conversion (see §3.3); this transitions the subscription from `TRIAL` to `ACTIVE`, cascades the tenant's `tenant_status` from `TRIAL` to `ACTIVE`, issues the first prepaid `Invoice` if the package's `pricing_model` is `PREPAID` or `HYBRID` (a pure `POSTPAID` package skips the prepaid issuance), emits a `SUBSCRIPTION_CREATED` event to `ACCOUNTING`, and writes a `TENANT_STATUS_CHANGE` audit entry. The conversion requires the tenant to currently be in `TRIAL`. Second, the trial may expire — when the system clock advances past `trial_expires_at` and no subscription on that tenant has transitioned to `ACTIVE`, the tenant moves from `TRIAL` to `TERMINATED`; any subscription still in `PENDING` is cancelled and the change is audit-logged. Third, a `PlatformAdmin` may delete an `ACTIVE` tenant directly — but only when its computed `outstanding_balance_cents` equals zero (otherwise the request is rejected with `ERR_OUTSTANDING_BALANCE_EXISTS`) and, if the tenant's `billing_entity_type` is `PARENT`, when no subsidiary tenants remain attached (otherwise `ERR_TENANT_HAS_SUBSIDIARIES`). Termination of an `ACTIVE` tenant cancels the active subscription, writes a `TENANT_STATUS_CHANGE` audit entry, and emits a `SUBSCRIPTION_CHANGED` event to `ACCOUNTING`.

A tenant in `TRIAL` status that is the target of any update or substantive operation only accepts the operations explicitly modeled in §3 — operations whose preconditions name a different `tenant_status` set are rejected with `ERR_TENANT_STATUS_INVALID`. A `PlatformAdmin` may patch the `legal_name`, `contact_email`, or `contact_phone` of any tenant; a `TenantAdmin` may patch only its own (cross-tenant patch attempts go through the §2.1 cross-tenant rejection, not the patch).

### 3.3. Subscription Lifecycle: Provision, Convert, Cancel

A subscription begins life when a `TenantAdmin` (or a `PlatformAdmin`) creates a new subscription on a tenant that is currently in `TRIAL`. The create payload supplies a `package_code` and optionally a `selected_addons` array. The system resolves the package by finding the `PackageVersion` with the largest `effective_from` not exceeding the current timestamp, validates that the resolved package's `currency` equals the tenant's `currency` (otherwise `ERR_CURRENCY_MISMATCH`), locks `package_version_id` to the resolved version, sets `cycle_start` to the current timestamp and `cycle_end` to that plus the package's billing-cycle period (one calendar month for `MONTHLY`, three for `QUARTERLY`, twelve for `ANNUAL`), initializes `quota_consumed` to an empty map, and persists the subscription with `subscription_status` of `TRIAL` and `payment_status` of `CURRENT`. The creation is audit-logged with action `SUBSCRIPTION_CREATE`. The pre-existing tenant `tenant_status` of `TRIAL` is itself a precondition; attempting to create a subscription on a tenant whose status is anything other than `TRIAL` yields `ERR_TENANT_STATUS_INVALID`.

Trial conversion advances the subscription from `TRIAL` to `ACTIVE`. The conversion endpoint accepts an optional `version` for OCC. It cascades the tenant from `TRIAL` to `ACTIVE` if the tenant was still in `TRIAL`, resets `cycle_start` to the moment of conversion and recomputes `cycle_end` accordingly, issues a `PREPAID` `Invoice` when the resolved package's `pricing_model` is `PREPAID` or `HYBRID`, emits a `SUBSCRIPTION_CREATED` event to `PAYMENT_PAY`, and audit-logs a `SUBSCRIPTION_CREATE` action. Subscription preconditions require the subscription's status to be exactly `TRIAL`; tenant preconditions allow either `TRIAL` or `ACTIVE`.

Cancelling a subscription is a delete operation that accepts an optional `version` for OCC. From `ACTIVE` (or `PENDING_DOWNGRADE`), cancellation moves the subscription to `CANCELLED`, issues a final `POSTPAID` invoice when the package's `pricing_model` includes a postpaid component and the current cycle has accumulated usage, emits a `SUBSCRIPTION_CHANGED` event to `CRM`, and writes a `SUBSCRIPTION_DOWNGRADE` audit entry with `change_type` of `CANCEL`. From `TRIAL`, cancellation moves the subscription directly to `CANCELLED` without issuing any invoice; the audit entry is still written with the same `SUBSCRIPTION_DOWNGRADE` action and `change_type` `CANCEL`. Cancellation may also happen as a cascade from a tenant transitioning `SUSPENDED → TERMINATED` — in that case the subscription's `subscription_status` lands at `CANCELLED` as part of the parent's termination side-effect.

### 3.4. Plan Changes: Upgrades, Downgrades, and Pro-Rated Reconciliation

Mid-cycle plan changes pull a tenant onto a different `PackageVersion` and reconcile money for the unconsumed portion of the cycle. The acting role is `TenantAdmin` (or `PlatformAdmin`). Both upgrade and downgrade carry an optional `version` for OCC and require a `target_package_code` naming the destination package. The downgrade endpoint additionally takes a `mode` query parameter whose value is either `END_OF_CYCLE` or `IMMEDIATE_REFUND`.

Upgrading requires the subscription to be in `ACTIVE` (otherwise `ERR_SUBSCRIPTION_STATUS_INVALID`), the tenant's `restriction_level` to be `NONE` (otherwise `ERR_TENANT_READ_ONLY`), and the target `PackageVersion.base_price_cents` to be strictly greater than the current package's `base_price_cents` (otherwise `ERR_NOT_AN_UPGRADE`). On success, the system replaces `package_version_id` with the target's id, creates a `SubscriptionChange` entry with `change_type` of `UPGRADE`, `from_package_version_id` set to the prior id, `to_package_version_id` set to the new id, `effective_at` set to the current timestamp, and `prorated_charge_cents` set to a positive (charge) amount computed by the proration rule below, issues a prorated `Invoice` whose `line_items` reflect that charge, resets `quota_consumed` to an empty map for the remainder of the cycle (the quota carry-forward rule below governs whether any quota survives the change), emits a `SUBSCRIPTION_CHANGED` event to `ACCOUNTING`, and audit-logs `SUBSCRIPTION_UPGRADE`.

Downgrading also requires the subscription in `ACTIVE` and the target's `base_price_cents` to be strictly less than the current package's `base_price_cents` (otherwise `ERR_NOT_A_DOWNGRADE`). Behavior then forks on `mode`. When `mode` is `END_OF_CYCLE`, the subscription moves to `PENDING_DOWNGRADE`, the system records the target on `pending_change_package_version_id`, and a `SubscriptionChange` entry is created with `change_type` `DOWNGRADE_END_OF_CYCLE`, `effective_at` equal to the current `cycle_end`, and `prorated_charge_cents` of zero — no money moves immediately; the downgrade takes effect at the next cycle rollover. When `mode` is `IMMEDIATE_REFUND`, the operation additionally requires the current package's `pricing_model` to be `PREPAID` or `HYBRID` (you cannot refund money you have not yet charged on a pure `POSTPAID` plan). The subscription's status remains `ACTIVE`, but `package_version_id` is replaced with the target's id, `prorated_charge_cents` is computed to a negative value (refund) via the proration rule below, a `CreditNote` is issued with `origin` of `REFUND_DOWNGRADE` and `amount_cents` equal to the absolute value of the refund, auto-applied to the most recent `ISSUED` invoice for this subscription (its `applied_to_invoice_id` becomes that invoice's id and `applied_cents` records the cents consumed), `quota_consumed` is reset to an empty map, a `SUBSCRIPTION_CHANGED` event is emitted to `ACCOUNTING`, and `SUBSCRIPTION_DOWNGRADE` is audit-logged.

The proration computation determines `prorated_charge_cents` deterministically. Let the cycle length in whole days be the count of whole days between `cycle_start` and `cycle_end`. Let elapsed days be the floor of the count of days between `cycle_start` and the current request timestamp. Remaining days is the cycle length minus the elapsed days. Old per-day cents is the current package's `base_price_cents` divided by the cycle length (kept in unrounded fractional cents). New per-day cents is the target package's `base_price_cents` divided by the cycle length (also unrounded). The unrounded prorated amount is the new per-day cents minus the old per-day cents, multiplied by the remaining days. Rounding to integer cents is applied only at the very last step using round-half-up. For an upgrade (forward-looking variant), this expression evaluates to a positive integer that becomes the charge. For an immediate-refund downgrade (chronological-refund variant), the same arithmetic naturally produces a negative integer because the new per-day rate is lower than the old — the sign convention is that the refund is the negative result, and the rounding is performed on the signed integer at the final step.

The cycle rollover itself happens when the clock advances such that the current timestamp is at or past `cycle_end`. For a subscription in `PENDING_DOWNGRADE`, this rollover sets `package_version_id` to the value of `pending_change_package_version_id`, clears `pending_change_package_version_id`, sets the new `cycle_start` to the old `cycle_end` and the new `cycle_end` to that plus the new package's billing-cycle period, applies the quota carry-forward rule below, resets `quota_consumed` to an empty map, and issues the next-cycle `Invoice` for the new package (a `PREPAID` or `HYBRID` pricing model issues immediately; pure `POSTPAID` accumulates and issues at the next rollover). The subscription's status transitions from `PENDING_DOWNGRADE` back to `ACTIVE` as part of this rollover.

Subscription change history is exposed as an immutable list under each subscription; each `SubscriptionChange` entry carries `id`, `created_at`, `subscription_id`, `tenant_id`, `change_type`, `from_package_version_id`, `to_package_version_id`, `effective_at`, and `prorated_charge_cents` — no `updated_at`, no `version`.

### 3.5. Quota Carry-Forward Rule

When a cycle rolls over for a subscription in `PENDING_DOWNGRADE`, or when the cycle simply advances at its scheduled `cycle_end`, the system applies a quota carry-forward rule. Carry-forward applies only when the new package's `billing_cycle` is `ANNUAL` and its `pricing_model` is `PREPAID` or `HYBRID`. In that case, the system carries unused seats from the prior cycle: `quota_carry_forward['seats']` is set to the maximum of zero and the old `included_quotas['seats']` minus the old `quota_consumed['seats']`. All other metrics — `api_calls`, `storage_gb`, `bandwidth_gb`, `active_users` — do not carry forward and are absent from `quota_carry_forward`. For any other combination of `billing_cycle` and `pricing_model`, `quota_carry_forward` is set to an empty map and nothing carries.

A separate rule supersedes the above on any package change (whether upgrade or immediate-refund downgrade, regardless of cycle alignment): both `quota_carry_forward` and `quota_consumed` are reset to empty maps. A plan change therefore always wipes prior consumption.

### 3.6. Add-On Selection and Currency Discipline

A subscription's `selected_addons` array lists the codes of currently active add-ons drawn from the resolved package's `addons` catalog. Each entry in `addons` declares its `code` and its `monthly_price_cents`. At invoice issuance, the system adds the sum of the `monthly_price_cents` of every entry in `selected_addons` as add-on line items. Currency discipline cuts across the catalog: a subscription is provisioned only when the resolved `PackageVersion.currency` equals the owning tenant's `currency`, and the same equality is required when upgrading or downgrading to a different version (each plan-change request re-resolves the package and revalidates currency); mismatch yields `ERR_CURRENCY_MISMATCH`.

### 3.7. Usage Metering, Idempotency, and Late-Arrival Handling

Tenants and platform operators stream consumption into the system through usage ingestion. Each usage submission carries a caller-supplied `idempotency_key` unique per metric event, a `metric` drawn from `API_CALL`, `STORAGE_GB`, `BANDWIDTH_GB`, or `ACTIVE_USER`, a non-negative integer `quantity` (negative quantities are rejected with `ERR_INVALID_USAGE_QUANTITY`), an `event_timestamp` in ISO 8601 UTC reflecting when the metered event actually occurred (which may pre-date ingestion), and an `ingestion_mode` of `REALTIME` or `BATCH`. The `(subscription_id, idempotency_key)` pair is globally unique on `UsageRecord` — submitting the same key with an identical body returns the originally persisted record with HTTP 201, whereas a conflicting body yields `ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY`.

The system attributes each ingestion to a billing cycle by comparing `event_timestamp` to the subscription's persisted cycle history. The window for accepting late-arriving events is seven days: an `event_timestamp` earlier than the current `cycle_start` minus seven days is rejected with `ERR_USAGE_TOO_LATE`. Inside the seven-day window, the resolution rule is as follows. If a persisted cycle `[cs, ce)` on this subscription contains `event_timestamp` (that is, `cs` is at or before `event_timestamp` and `event_timestamp` is strictly before `ce`), `attributed_cycle_start` is set to that cycle's `cs`. If `event_timestamp` is at or past the current cycle's `cycle_end` — a future-dated event — `attributed_cycle_start` is set to the current cycle's `cycle_start`. Otherwise, the event falls inside the seven-day late-arrival window but its natural target cycle is already sealed (already invoiced); in that case, `attributed_cycle_start` is also set to the current cycle's `cycle_start`, because a sealed cycle cannot be modified retroactively. The persisted `UsageRecord` records the resolved `attributed_cycle_start` along with `subscription_id`, `tenant_id`, `idempotency_key`, `metric`, `quantity`, `event_timestamp`, and `ingestion_mode`. The `archived` flag begins `false`.

The subscription's `quota_consumed[metric]` is incremented by `quantity` if and only if `attributed_cycle_start` equals the current cycle's `cycle_start` — events attributed to prior cycles are stored but do not bump the live counter. The idempotent replay path never double-increments: when the system returns the existing record, no quota mutation occurs.

When `restriction_level` is `FEATURE_RESTRICTED` and a `metric` of `API_CALL` would push `quota_consumed['api_calls']` past the resolved `PackageVersion.included_quotas['api_calls']`, ingestion is rejected with `ERR_TENANT_FEATURE_RESTRICTED`.

### 3.8. Usage Archive

An administrative archive sweep marks `UsageRecord.archived` to `true` for records older than a supplied cutoff in ISO 8601 form. The sweep accepts the cutoff parameter `cutoff_iso` and returns the number of records affected as `archived_count`. Archived records remain queryable through the usage list endpoint by filtering on `archived`; the list supports filtering by `metric` and `cycle_start` as well.

### 3.9. Invoice Lifecycle and Bill Total Calculation

An invoice begins in `DRAFT` status. While in `DRAFT`, a `PlatformAdmin` or `BillingOperator` may apply a `discount_cents` value through a patch — the value must be greater than or equal to zero and less than or equal to the current `subtotal_cents` (otherwise `ERR_DISCOUNT_EXCEEDS_SUBTOTAL`). The patch accepts an optional `version` for OCC, recomputes `subtotal_cents`, `tax_cents`, and `total_cents` via the bill total calculation below, and audit-logs `INVOICE_ADJUSTMENT`.

Issuance moves the invoice from `DRAFT` to `ISSUED`. Issuance is performed by a `PlatformAdmin` or `BillingOperator` explicitly, or by the system automatically at cycle rollover, trial conversion, upgrade-time proration, and downgrade-time refund. On issuance, the system finalizes `subtotal_cents`, `tax_cents`, and `total_cents` via the bill total calculation, freezes the `line_items` array, sets `due_at`, and emits an `INVOICE_ISSUED` event to `ACCOUNTING`. Issuance is forbidden on any invoice that is not in `DRAFT`, which surfaces as `ERR_INVOICE_STATUS_INVALID`. Per-cycle uniqueness on `(subscription_id, cycle_start, pricing_model)` is enforced at issuance, with `ERR_INVOICE_CYCLE_ALREADY_ISSUED` as the loser's response.

The bill total calculation produces `subtotal_cents`, `tax_cents`, and `total_cents` from the subscription's `quota_consumed`, the resolved package's `included_quotas`, `tiered_brackets`, `overage_rates`, `pricing_model`, `base_price_cents`, and `addons`, the invoice's `discount_cents`, the tenant's unapplied `CreditNote` records, and the tenant's jurisdiction. The evaluation order is pinned and tax is not recomputed after credits are applied. Step by step:

1. **Base line.** When the package's `pricing_model` is `POSTPAID`, the base line is zero. Otherwise the base line equals the package's `base_price_cents`.
2. **Tiered lines.** For each metric in the package's `tiered_brackets`, the consumed amount above the included quota is computed as `quota_consumed[metric]` minus `included_quotas[metric]`. When that result is zero or negative the metric contributes nothing. When it is positive, the system walks the bracket list for that metric in order; for each bracket, the bracket's capacity is its `upper_bound` (with a null `upper_bound` treated as infinite) minus the included quota minus the capacities of all preceding brackets for the metric, then takes the minimum of the remaining consumption and that capacity, adds the taken units multiplied by the bracket's `unit_price_cents` to the running tiered total, decrements the remaining consumption by the units taken, and stops when remaining consumption falls to zero or below.
3. **Overage lines.** For each metric in the package's `overage_rates`, any consumption uncovered by tier brackets (zero if there are no brackets for that metric, otherwise the residual after the bracket walk) is multiplied by the metric's overage rate in cents per unit, and accumulated into the overage line total.
4. **Add-on lines.** The sum of the `monthly_price_cents` of every add-on whose code appears in the subscription's `selected_addons`.
5. **Subtotal.** `subtotal_cents` is the sum of base line, tiered lines, overage lines, and add-on lines.
6. **Discount.** The effective discount is `discount_cents` clamped to the closed interval from zero to `subtotal_cents`; the taxable base is `subtotal_cents` minus the effective discount.
7. **Tax.** `tax_cents` is computed from the taxable base, the tenant's `Jurisdiction`, the rounding mode, and the line breakdown — see the tax computation below.
8. **Credit.** `credit_applied_cents` is the sum of unapplied `CreditNote.amount_cents` for the tenant, clamped to the closed interval from zero to the taxable base plus `tax_cents`. Credits are applied to the gross-of-tax bill; tax is not recomputed after credit application.
9. **Late fee.** `late_fee_cents` is the late-fee accrual on the invoice as of the current clock (zero on a freshly-issued invoice; non-zero when the bill is being recomputed during dunning). The accrual rule is defined in §3.10.
10. **Total.** `total_cents` is the taxable base plus `tax_cents` minus `credit_applied_cents` plus `late_fee_cents`.

The tax computation respects the tenant's jurisdiction. The applicable record is the `Jurisdiction` whose `jurisdiction_code` equals the tenant's `jurisdiction_code`; it declares a `tax_rate_bps` in basis points (875 means 8.75%) and a `rounding_mode` of `PER_LINE` or `TOTAL`. When `rounding_mode` is `PER_LINE`, the system computes, for each line item (base, tiered, overage, and add-on lines individually), the line's `line_total_cents` multiplied by `tax_rate_bps` divided by 10000 and rounded half-up to integer cents, sums those rounded per-line taxes, then subtracts the discount's tax-equivalent (discount in cents multiplied by `tax_rate_bps` divided by 10000, rounded half-up). When `rounding_mode` is `TOTAL`, the system first computes the taxable base (`subtotal_cents` minus the effective discount), multiplies by `tax_rate_bps`, divides by 10000, and rounds half-up to integer cents in a single step. The two modes will in general produce different `tax_cents` for the same inputs.

Once issued, the invoice can accumulate one or more payments (see §3.11). If `amount_paid_cents` is strictly between zero and `total_cents`, the invoice transitions from `ISSUED` to `PARTIALLY_PAID` and `amount_due_cents` (the maximum of zero and `total_cents` minus `amount_paid_cents`) is recomputed; a `PAYMENT_RECEIVED` event is emitted to `PAYMENT_PAY`. If `amount_paid_cents` reaches `total_cents` on the first payment, the invoice moves directly from `ISSUED` to `PAID`. If a payment on a `PARTIALLY_PAID` invoice brings `amount_paid_cents` up to `total_cents`, the invoice transitions to `PAID`. Both `PAID` paths cascade to set `subscription_status` `payment_status` to `CURRENT` (when no other unpaid invoices remain for that subscription) and `restriction_level` to `NONE` (when no other unpaid invoices remain for that tenant).

When the dunning sweep finds an `ISSUED` or `PARTIALLY_PAID` invoice for which the current timestamp is at or past `due_at` plus the tier-one grace window and `amount_due_cents` is positive, the invoice transitions to `OVERDUE`, the subscription's `payment_status` cascades to `OVERDUE_TIER1`, the tenant's `restriction_level` cascades to `READ_ONLY`, and `late_fee_cents` is recomputed. A payment that reaches `total_cents` plus `late_fee_cents` on an `OVERDUE` invoice transitions it to `PAID`, cascades the subscription's `payment_status` back to `CURRENT`, clears `restriction_level` to `NONE`, lifts the tenant from `SUSPENDED` back to `ACTIVE` if it was suspended, and recomputes `late_fee_cents` to zero. An overdue invoice on a tenant that transitions from `SUSPENDED` to `TERMINATED` cascades to `WRITTEN_OFF`, stops late-fee accrual, and emits a `SUBSCRIPTION_CHANGED` event to `ACCOUNTING`.

The `Invoice` resource further records `pricing_model` (copied from the `PackageVersion` at issuance), `currency` (always equal to the tenant's `currency` at issue time), and `credit_applied_cents` (the cents consumed by credit notes against this invoice).

### 3.10. Late-Fee Accrual

Late-fee accrual runs on each `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` invoice whose `amount_due_cents` is greater than zero, both during the dunning sweep and just before the zero-out check on each payment. The system computes days past due as the floor of the duration from `due_at` to the current clock measured in whole days. When days past due is zero or negative, `late_fee_cents` is zero. When days past due is greater than zero and at most thirty (inclusive of thirty), `late_fee_cents` is round-half-up of `amount_due_cents` multiplied by 100 and divided by 10000 — equivalently one percent of `amount_due_cents` rounded half-up to integer cents. When days past due is greater than thirty and at most sixty (inclusive of sixty; days past due equal to thirty-one selects this bracket), `late_fee_cents` is round-half-up of `amount_due_cents` multiplied by 250 and divided by 10000 — equivalently two-and-a-half percent. When days past due is greater than sixty, `late_fee_cents` is round-half-up of `amount_due_cents` multiplied by 500 and divided by 10000 — equivalently five percent. Reactivation on payment resets `late_fee_cents` to zero on the just-paid invoice.

### 3.11. Payments, Credit Notes, and the Tenant Outstanding Balance

A payment posts cash against exactly one invoice. The payload carries the targeted `invoice_id`, a positive integer `amount_cents` (zero or negative is rejected with `ERR_INVALID_AMOUNT`), a `currency` that must equal the invoice's `currency` (otherwise `ERR_CURRENCY_MISMATCH`), and a caller-supplied `external_reference` that is globally unique per tenant. A duplicate `(tenant_id, external_reference)` with a conflicting payload yields `ERR_DUPLICATE_PAYMENT_REFERENCE`, while an identical replay returns the originally persisted `Payment` at HTTP 201. The persisted record stores `tenant_id`, `invoice_id`, `amount_cents`, `currency`, `external_reference`, and `payment_status` (which is `RECEIVED` on creation; the system does not transition to `REVERSED` on its own). Payments are immutable thereafter and carry only `id` and `created_at` as common fields.

Each payment allocates against its target invoice and triggers the invoice and cascade transitions described in §3.9. The system recomputes the invoice's `amount_paid_cents` (sum of the `amount_cents` of all payments allocated to that invoice) and `amount_due_cents`, then re-runs late-fee accrual immediately before the zero-out check so a payment that fully clears the invoice resets `late_fee_cents` to zero in the same step. Any payment that fully clears the invoice cascades through the subscription's `payment_status` and the tenant's `restriction_level` and `tenant_status` as described above.

Credit notes flow in two directions. The downgrade-refund path automatically issues one with `origin` of `REFUND_DOWNGRADE`. A `BillingOperator` or `PlatformAdmin` may issue a credit note manually with `origin` of `MANUAL_ADJUSTMENT` or `TAX_CORRECTION`; the payload supplies `origin`, `amount_cents` (positive), and optionally an `applied_to_invoice_id` naming the invoice to consume the credit against. When `applied_to_invoice_id` is supplied, the system recomputes that invoice's totals via the bill total calculation (incorporating the new credit), writes a `CREDIT_ISSUE` audit entry, and records `applied_cents` (the cents actually consumed; less than or equal to `amount_cents`). An unapplied credit note has `applied_to_invoice_id` null and `applied_cents` zero. Credit-note records are immutable beyond their initial creation and the system-managed application fields.

The tenant's `outstanding_balance_cents` is a computed field, recomputed on every Invoice status change, every Payment creation, every CreditNote application, every dunning run, and every reactivation. It equals the sum of `amount_due_cents` for every Invoice owned by this tenant whose `invoice_status` is `ISSUED`, `PARTIALLY_PAID`, or `OVERDUE` and whose `currency` equals the tenant's `currency` — invoices in `WRITTEN_OFF`, `PAID`, or `DRAFT` are excluded. The tenant's `active_subscription_id` is likewise computed: it equals the `id` of the unique subscription on this tenant whose `subscription_status` is `TRIAL` or `ACTIVE`, or null if none exists.

### 3.12. Dunning, Suspension, and Reactivation

Dunning is the controlled escalation that responds to unpaid invoices. The cycle begins when the clock crosses an invoice's `due_at` while the invoice is still `ISSUED` or `PARTIALLY_PAID`: the subscription's `payment_status` transitions from `CURRENT` to `DUE`, `late_fee_cents` on that invoice is recomputed, and the tenant's `restriction_level` is unchanged at this stage.

Subsequent runs of the dunning sweep advance the tier as time passes. After the tier-one grace window has elapsed past `due_at` with `amount_due_cents` still positive, the subscription advances from `DUE` to `OVERDUE_TIER1` (the invoice itself transitions to `OVERDUE`), the tenant's `restriction_level` advances from `NONE` to `READ_ONLY`, and late-fee accrual continues. Once the unpaid invoice has lingered past the tier-two threshold, the subscription advances from `OVERDUE_TIER1` to `OVERDUE_TIER2` and the tenant's `restriction_level` advances from `READ_ONLY` to `FEATURE_RESTRICTED`. Once it passes the tier-three threshold, the subscription advances from `OVERDUE_TIER2` to `OVERDUE_TIER3`, the tenant's `tenant_status` cascades from `ACTIVE` to `SUSPENDED`, the tenant's `restriction_level` is overridden to `NONE` because suspension supersedes feature restriction, a `TENANT_SUSPENDED` event is emitted to `CRM`, and a `TENANT_STATUS_CHANGE` audit entry is written.

A tenant that has been `SUSPENDED` for more than the termination grace period (thirty days) transitions on the next dunning run from `SUSPENDED` to `TERMINATED`. This cancels the active subscription (setting `subscription_status` to `CANCELLED`), writes off all `OVERDUE` invoices (setting `invoice_status` to `WRITTEN_OFF` and stopping further late-fee accrual), emits a `SUBSCRIPTION_CHANGED` event to `ACCOUNTING`, and audit-logs the status change.

Reactivation on payment is the inverse path. A payment that brings the targeted invoice's `amount_due_cents` to zero, and after which the tenant's `outstanding_balance_cents` is also zero, lifts every dunning indicator in one step: `payment_status` is reset to `CURRENT`, `restriction_level` is reset to `NONE`, `late_fee_cents` is recomputed to zero on the just-paid invoice, and — if the tenant's `tenant_status` was `SUSPENDED` — `tenant_status` is restored to `ACTIVE` and a `TENANT_REACTIVATED` event is emitted to `CRM`. The four entry tiers (`DUE`, `OVERDUE_TIER1`, `OVERDUE_TIER2`, `OVERDUE_TIER3`) all converge on the same payment-driven exit to `CURRENT` provided the post-allocation balance is zero. When the post-allocation balance is greater than zero, no tier reversal happens — the subscription stays at its current dunning tier.

The tier thresholds (tier-one, tier-two, tier-three grace day counts, and the suspension-to-termination grace of thirty days) and the late-fee bracket rates (`RATE_BPS_TIER1` of one hundred basis points, `RATE_BPS_TIER2` of two hundred fifty basis points, `RATE_BPS_TIER3` of five hundred basis points) are system constants applied uniformly across all tenants. The late-fee bracket selection is governed by §3.10 — based on whole days past `due_at`, with strict inclusive boundaries at thirty and sixty days.

### 3.13. Tax Jurisdictions

A jurisdiction record is configuration data declaring a unique `jurisdiction_code` (e.g., `US-CA`, `DE`, `JP`), a `tax_rate_bps` in basis points, and a `rounding_mode` of `PER_LINE` or `TOTAL`. A `PlatformAdmin` defines new jurisdictions; everyone with billing visibility can list them. The semantics of the two `rounding_mode` values are pinned in §3.9's bill total calculation: `PER_LINE` rounds tax on each line then sums, while `TOTAL` sums lines then rounds tax once. The two will generally produce different `tax_cents` for the same gross inputs.

### 3.14. Test-Harness Capabilities

Because many transitions in this system are driven by the passage of time — trial expiry, invoice due-date crossings, dunning tier advances, cycle rollovers — the API exposes three privileged capabilities for deterministic test driving. All three are `PlatformAdmin`-only. A clock-advance capability accepts a `seconds` delta in its body and advances the logical clock by that delta, returning the new `now` instant; this may trigger trial-expiry-driven `TRIAL → TERMINATED` (when the new instant is past `trial_expires_at` and no subscription has gone `ACTIVE`) and `PENDING_DOWNGRADE → ACTIVE` cycle rollovers, and surfaces invoices whose `due_at` is now past. A dunning sweep capability runs the scan that advances `payment_status` tiers, cascades `restriction_level` and `tenant_status` upgrades, recomputes `late_fee_cents` on each unpaid invoice, and reports `scanned` and `transitioned` counts. An archive sweep capability accepts a `cutoff_iso` ISO 8601 timestamp and flips the `archived` flag on `UsageRecord` rows older than the cutoff, returning the resulting `archived_count`.

## 4. Endpoint Definitions

All listed endpoints conform to the RBAC matrix below. New-resource creation returns HTTP 201 with the created resource in `data`; in-place modifications return HTTP 200 with the updated resource; deletions that have no body return HTTP 204. List endpoints return HTTP 200 with an array in `data` and the pagination block in `meta`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /tenants | Create a tenant (TRIAL by default) | PlatformAdmin |
| GET | /tenants | List tenants across the platform | PlatformAdmin |
| GET | /tenants/{id} | Get tenant | PlatformAdmin, BillingOperator, TenantAdmin |
| PATCH | /tenants/{id} | Update tenant profile and contact fields | PlatformAdmin, TenantAdmin |
| DELETE | /tenants/{id} | Terminate tenant (requires zero outstanding balance and no subsidiaries) | PlatformAdmin |
| POST | /packages | Define a new PackageVersion | PlatformAdmin |
| GET | /packages | List packages | PlatformAdmin, BillingOperator, TenantAdmin |
| GET | /packages/{id} | Get a specific PackageVersion | PlatformAdmin, BillingOperator, TenantAdmin |
| POST | /tenants/{tenant_id}/subscriptions | Create subscription in TRIAL state | PlatformAdmin, TenantAdmin |
| GET | /tenants/{tenant_id}/subscriptions/{id} | Get subscription | PlatformAdmin, BillingOperator, TenantAdmin |
| POST | /tenants/{tenant_id}/subscriptions/{id}/convert | Trial-to-paid conversion | PlatformAdmin, TenantAdmin |
| POST | /tenants/{tenant_id}/subscriptions/{id}/upgrade | Immediate upgrade with prorated charge | PlatformAdmin, TenantAdmin |
| POST | /tenants/{tenant_id}/subscriptions/{id}/downgrade | Downgrade end-of-cycle or immediate-refund | PlatformAdmin, TenantAdmin |
| DELETE | /tenants/{tenant_id}/subscriptions/{id} | Cancel subscription | PlatformAdmin, TenantAdmin |
| GET | /tenants/{tenant_id}/subscriptions/{id}/changes | List subscription change history | PlatformAdmin, BillingOperator, TenantAdmin |
| POST | /tenants/{tenant_id}/subscriptions/{id}/usage | Ingest a usage record (real-time or batch) | PlatformAdmin, TenantAdmin |
| GET | /tenants/{tenant_id}/subscriptions/{id}/usage | List usage records | PlatformAdmin, BillingOperator, TenantAdmin |
| GET | /tenants/{tenant_id}/invoices | List invoices for tenant | PlatformAdmin, BillingOperator, TenantAdmin |
| GET | /tenants/{tenant_id}/invoices/{id} | Get invoice | PlatformAdmin, BillingOperator, TenantAdmin |
| PATCH | /tenants/{tenant_id}/invoices/{id} | Apply discount before issuance (DRAFT only) | PlatformAdmin, BillingOperator |
| POST | /tenants/{tenant_id}/invoices/{id}/issue | Issue an invoice (DRAFT to ISSUED) | PlatformAdmin, BillingOperator |
| POST | /tenants/{tenant_id}/invoices/{id}/payments | Apply payment to invoice | PlatformAdmin, BillingOperator, TenantAdmin |
| POST | /tenants/{tenant_id}/credit-notes | Issue a manual credit note | PlatformAdmin, BillingOperator |
| GET | /tenants/{tenant_id}/credit-notes | List credit notes for tenant | PlatformAdmin, BillingOperator, TenantAdmin |
| POST | /jurisdictions | Define a tax jurisdiction | PlatformAdmin |
| GET | /jurisdictions | List jurisdictions | PlatformAdmin, BillingOperator |
| GET | /tenants/{tenant_id}/sync-events | List sync events emitted for this tenant | PlatformAdmin, BillingOperator |
| GET | /tenants/{tenant_id}/audit-logs | List audit logs for this tenant | PlatformAdmin, BillingOperator, TenantAdmin |
| POST | /_clock/advance | Advance the logical system clock by a delta | PlatformAdmin |
| POST | /_dunning/run | Run the dunning sweep | PlatformAdmin |
| POST | /_archive/run | Run the usage archive sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_MISSING_ROLE | 401 |
| ERR_AUTH_MISSING_USER | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_CROSS_TENANT_ACCESS | 403 |
| ERR_TENANT_READ_ONLY | 403 |
| ERR_TENANT_FEATURE_RESTRICTED | 403 |
| ERR_TENANT_NOT_FOUND | 404 |
| ERR_SUBSCRIPTION_NOT_FOUND | 404 |
| ERR_INVOICE_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_JURISDICTION_NOT_FOUND | 404 |
| ERR_TENANT_STATUS_INVALID | 409 |
| ERR_SUBSCRIPTION_STATUS_INVALID | 409 |
| ERR_INVOICE_STATUS_INVALID | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_SUBSCRIPTION_CHANGE_IN_FLIGHT | 409 |
| ERR_DUPLICATE_USAGE_IDEMPOTENCY_KEY | 409 |
| ERR_DUPLICATE_PAYMENT_REFERENCE | 409 |
| ERR_INVOICE_CYCLE_ALREADY_ISSUED | 409 |
| ERR_PACKAGE_VERSION_DUPLICATE | 409 |
| ERR_INVALID_PARENT_TENANT | 422 |
| ERR_CURRENCY_MISMATCH | 422 |
| ERR_NOT_AN_UPGRADE | 422 |
| ERR_NOT_A_DOWNGRADE | 422 |
| ERR_USAGE_TOO_LATE | 422 |
| ERR_INVALID_AMOUNT | 422 |
| ERR_INVALID_USAGE_QUANTITY | 422 |
| ERR_DISCOUNT_EXCEEDS_SUBTOTAL | 422 |
| ERR_OUTSTANDING_BALANCE_EXISTS | 422 |
| ERR_TENANT_HAS_SUBSIDIARIES | 422 |
