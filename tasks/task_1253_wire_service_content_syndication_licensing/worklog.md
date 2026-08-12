# Worklog — task_1253_wire_service_content_syndication_licensing

## Step 1: Create Task Directory — 2026-08-12T09:04:27.000Z

Pre-assigned output folder `tasks/task_1253_wire_service_content_syndication_licensing` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

Difficulty parameter: "hard than expert level!" (pass-through to prd-bench-scaffold-generator at Step 2).

## Step 2: Generate Scaffold — 2026-08-12T09:21:26.000Z

All three files exist, are non-empty, parse as YAML, and lint is clean.

## Summary

Generated scaffold for task 1253 (Wire Service & Content Syndication Licensing) at `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/`:

**Counts**
- Entities: 11 (ContentPackage, SubscriberTier, Feed, Subscriber, Subscription, Entitlement, Article, Asset, Publication, Invoice, ClockCheckpoint)
- State machines: 6 (Article, Subscription, Subscriber, Entitlement, Invoice, Publication) — non-linear shapes include Article's PUBLISHED↔WITHDRAWN cycle and Subscription's ACTIVE↔SUSPENDED branching
- Calculations: 5 (price_monthly_subscription with provisional/final variants, tier_resolution, compute_overage_cents, member_credit_grant, member_credit_apply_to_invoice)
- Endpoints: 58
- Error codes: 14
- Roles: 7 (PlatformAdmin, SalesOps, Editor, Legal, Auditor, Billing, SubscriberRep — segregation-of-duties model with entity_backed SubscriberRep)
- Difficulty-design instances: 18 (2 per rule × 9 rules)
- Corner-design instances: 21

**Lint verdict (verbatim)**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**How "hard than expert level!" was applied**
- **Expert-band surface, dense coupling**: 11 entities (top of Expert), 58 endpoints (well above the 20–32 expert range) — but difficulty comes from coupling, not volume: every article/action chain walks through tier-resolution, entitlement, embargo, quota, and member-credit logic.
- **9/9 difficulty rules at 2 instances each (18 total)**, including: dual-variant pricing (final vs provisional, on different entity domains — Subscription vs Article), combinatorial formulas in two different modes (tiered multi-input formula vs nested-rounding aggregation), cyclic + branching state machines on different entities, two transitive cascades from different triggers (Subscriber-suspend depth-3 chain vs Article-takedown depth-2 chain with credit debit), two priority-pair conflicts (state vs temporal; referential vs constraint), two boundary-precision checks (inclusive min_audience; quota exact-crossing), two cross-entity state dependencies (Subscription→Subscriber; Publication→Entitlement), two distinct interval-overlap semantics (half-open embargo window vs closed 30-day termination notice), and two compensating invariants (member credit conservation vs republish-count monthly bucket invariant).
- **Cross-cutting layers**: optimistic_concurrency (OCC on Subscriber.version and Article.version via expected_*_version), derived_field_reconciliation (monthly_price_cents, overage_cents), rate_threshold_triggers (tier min/max boundary; quota), scheduled_actions (embargo_until, renewal_due_at, termination notice), cascading_side_effects.
- **Segregation of duties** role model — Legal takedown, Editor publish, Auditor flag/dismiss, Billing invoice, SalesOps subscriber lifecycle, SubscriberRep external republication — so role-conflict negative tests are load-bearing.

## Step 3: Copy Shared Files — 2026-08-12T09:21:26.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1253_wire_service_content_syndication_licensing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T09:31:57.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/workspace/PRD.md` — 283 lines, 41 KB, verified on disk and non-empty.

## Section list
- **§1 Introduction** (2 paragraphs, business-context angle)
- **§2 Global Specifications & System-Wide Principles**: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block, byte-identical to the skill's canonical source) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Monetary Precision and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Validation Order and Error Precedence · 2.9 Cascading State Propagation and Hierarchical Consistency · 2.10 Nested Resource Retrieval
- **§3 Business Logic & Workflows** (7 subsections, entity-lifecycle grouping): 3.1 Catalogue Configuration (Packages/Tiers/Feeds) · 3.2 Subscriber Onboarding and Account Lifecycle · 3.3 Subscription Lifecycle (Activation/Pricing/Suspension/Renewal) · 3.4 Entitlements and Feed Access · 3.5 Editorial Pipeline (Articles/Embargoes/Takedowns/Member Credits) · 3.6 Republication, Quotas, Rights Enforcement, and Audit · 3.7 Billing (Invoices/Overage Aggregation/Member Credit Application)
- **§4 Endpoint Definitions** — 58-row table, 4 columns only (Method, Path, Description, Authorized Roles)
- **§5 Error Code Catalogue** — 14-row table, 2 columns only (Error ID, HTTP Status)

## Coverage audit (all machine-checked against SCAFFOLD.yaml)
- **Entities**: all 11 covered in prose — ContentPackage, SubscriberTier, Feed (§3.1), Subscriber (§3.2), Subscription (§3.3), Entitlement (§3.4), Article + Asset (§3.5), Publication (§3.6), Invoice (§3.7), ClockCheckpoint (§2.4, with explicit note that `updated_at`/`version` are absent per `common_fields: false`)
- **State machines**: all 6 fully rendered with from/to states, preconditions paired to error IDs, and every side effect — Article (7 transitions incl. sibling PUBLISHED/WITHDRAWN→TAKEN_DOWN), Subscription (6 transitions incl. system expiry sweep), Subscriber (4 transitions incl. 30-day notice rule), Entitlement (LIVE→REVOKED), Invoice (3 transitions), Publication (2 transitions incl. dismiss-refund)
- **Calculations**: all 5 in precise prose, no pseudocode — tier_resolution (inclusive min / exclusive-or-null max, zero→`ERR_NO_MATCHING_TIER`, many→`ERR_AMBIGUOUS_TIER`), price_monthly_subscription (gross = base × bp ÷ 10000 round-half-up; member discount limb; provisional variant ignoring both discount and credit balance), compute_overage_cents (bucket reset, increment, `within_quota` at ≤ quota, invoice-side sum over RECORDED/AUDIT_FLAGGED in month [start, next-start)), member_credit_grant (2000/5000/9000/14000 word brackets + 1500/PHOTO + 4000/VIDEO, all assets regardless of status), member_credit_apply_to_invoice (min-of waterfall, floor-zero total)
- **Validations**: all 12 priorities enumerated in explicit evaluation order in §2.8 with `applies_to` scopes; `ERR_VALIDATION` noted separately as unordered baseline
- **Endpoints**: all 58 in §4 table; every endpoint's side effects narrated in §3; every request-body key, query param, and path param backticked
- **Errors**: all 14 IDs mentioned in §2/§3 narrative; §5 table carries ID + status only
- **Roles**: all 7 named with exact spelling; `identity:` translated per role (6 opaque, SubscriberRep entity-backed with `X-User-ID` = Subscriber `id` and FK-compare semantics)

## Hard contract reports
- **Contract 1 (Field-Name Coverage)**: 56/56 entity fields, 39/39 endpoint inputs, 1/1 path params present in backticks — **PASS**
- **Contract 2 (Rule Coverage)**: 12/12 validations with priority expressed; 2/2 OCC rejections (write op + `expected_subscriber_version`/`expected_article_version` + `ERR_STALE_VERSION`/412, pure stale-version framing); 30/30 state transitions; 5/5 calculations; 12/12 validation conditions matchable to error IDs; all endpoint side effects and applies_to scopes expressed; structured field content (defaults, computed sources, integer-cents typing) reconstructible; sibling branches (cancel from ACTIVE vs SUSPENDED, terminate from ACTIVE vs SUSPENDED, takedown from PUBLISHED vs WITHDRAWN) at equal density — **PASS**
- **Contract 3 (§3 Path Purity)**: 320 backticked tokens scanned in §3; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — **PASS** (the `/wire` mount appears only in §1/§4, which is permitted)

## Leak confirmation
Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or read at any point; no sibling `task_*` directory was touched. The PRD contains no difficulty-tier labels, no worked-example numbers beyond the scaffold's own constants, and no `test_recipe` content — only scaffold-derived prose.

## Step 5: Generate Unit Tests — 2026-08-12T09:58:36.000Z

Done. Summary of what was generated and verified.

## Helper files written — `test_helpers/` (9 files)
- `types.py` — 11 entity TypedDicts + 13 enums. `ClockCheckpoint` (common_fields: false) omits `updated_at`/`version`; all others carry the full common quad.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (49 methods, all under `/wire`); bodyless POST transitions send `{}`.
- `api_errors.py` — `ApiErrorId` enum (14 IDs) + HTTP status map, registered with the framework via `set_error_http_status_map`.
- `assertions.py` — per-entity `assert_*` (uuid/timestamps/version/status membership), `assert_clock_checkpoint` asserting `updated_at`/`version` absence, `parse_instant`, invoice fiscal invariant checker.
- `factories.py` — input-field-only payload factories with uuid-unique codes/slugs.
- `constants.py` — thresholds (10000 bp denominator, 3-month commitment, 30-day notice, 60-day renewal notice, word-bracket cents 2000/5000/9000/14000, PHOTO 1500 / VIDEO 4000).
- `test_users.py` — 6 opaque-role shared headers + `make_subscriberrep_headers(subscriber_id)` builder (mandatory for the entity-backed SubscriberRep role; used by every republication call).
- `fixtures.py` — tiered composites: `set_clock`, creators, `create_draft_subscription`, `activate_subscription` (OCC token re-read via fresh GET so subscriber version is never stale in setup), `setup_active_subscription`, `setup_subscription_with_entitlement`, `create_published_article`, `publish_contributing_article`, `record_publication[_response]`, `setup_subscription_with_publications`, `create_draft_invoice`/`issue_invoice`/`setup_issued_invoice`, plus entity re-readers.
- `__init__.py` — barrel export (framework + PRD-specific).

## Test suite — `test_suite/` (conftest.py + 7 files, 55 tests)
- `test_01_catalogue_and_accounts.py` (5), `test_02_access_control.py` (8), `test_03_pricing_and_tiers.py` (9), `test_04_subscription_lifecycle.py` (10), `test_05_article_pipeline.py` (11), `test_06_republication.py` (7), `test_07_invoices_and_credit.py` (5).

## Per-instance disposition
- **Queue A (difficulty): 17 emitted × 2 tests = 34 tests; 1 skipped.**
  - SKIPPED `Difficulty/priority_pair_validation_conflict/state_vs_temporal_priority_on_republication` — fails the PRD-first unique-derivability filter. The instance expects `ERR_INVALID_STATE` when recording a republication against a WITHDRAWN article whose embargo is still in the future. But PRD §3.6 enumerates the republication gates (cross-account, LIVE entitlement, embargo-future, rights incl. TAKEN_DOWN) with no article-state check for WITHDRAWN, and §2.8 item 4 scopes the from-state check to "transition endpoints". A faithful PRD-only implementer would reject this recipe with `ERR_TEMPORAL_VIOLATION` (the embargo gate provably fires), so the asserted outcome is not uniquely derivable. Gap left as a gap — no placeholder emitted.
- **Queue B (corner): 21/21 emitted × 1 test = 21 tests.** No `excluded_because` stubs existed in the index.

## Verification status
- `python3 -m py_compile` passes on all 16 generated files; pytest collects 55 tests cleanly.
- Tag audit: every test function carries exactly one `Design:` line; all 55 tags resolve to real instances in the source yamls; coverage targets met (≥2 per emitted A instance, ≥1 per B instance).
- Verbatim-citation sweep: all 77 quoted PRD citations survive a whitespace-normalized literal grep of `workspace/PRD.md` (4 initial failures from markdown `**` bold markers were fixed by starting quotes after the bolded labels).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in generated comments/docstrings.

One translation note: for `Difficulty/non_linear_state_machine/article_withdraw_republish_cycle`, the design's trigger passes the post-publish version as `expected_article_version`, but withdraw is itself a mutation that advances the article version (PRD §2.5), so that token would be stale. The emitted tests pass the article's current (post-withdraw) version — the only PRD-consistent way to reach the instance's asserted outcome (PUBLISHED + EMBARGOED + version incremented).

## Step 6: Generate Implementation — 2026-08-12T09:58:36.000Z

All verification complete and the test server processes are cleaned up. Here is the summary.

## Implementation Summary

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/workspace/implementation/`):
- `app.py` — 60,615 bytes, single-file Flask server (store, envelope, auth, all routes, business logic)
- `start.sh` — 396 bytes, executable, foreground `exec python3 app.py`, binds 0.0.0.0, reads `$PORT` (default 10000), guarded dependency install (`python3 -c "import flask"` check before pip)
- `requirements.txt` — 11 bytes (`flask>=2.2`)

**Routes**: 58 registered vs 58 declared in SCAFFOLD.yaml — exact match, zero missing, zero extra (verified programmatically against `app.url_map`).

**Storage**: in-memory dicts only (`STORE` keyed by id); nothing persisted, nothing seeded. The only boot-time state is the PRD-mandated logical clock (`2026-05-01T00:00:00Z`) and its ClockCheckpoint shell. Verified: kill + relaunch via `start.sh` returns `total_count: 0` on all collections.

**State machines implemented**: Article (DRAFT→PUBLISHED→WITHDRAWN→PUBLISHED/TAKEN_DOWN with embargo/lift sub-states), Subscription (DRAFT→ACTIVE→SUSPENDED/EXPIRED/CANCELLED, renew), Subscriber (ACTIVE→SUSPENDED/TERMINATED with 30-day notice gate), Entitlement (LIVE→REVOKED), Invoice (DRAFT→ISSUED→PAID/VOIDED), Publication (RECORDED→AUDIT_FLAGGED→DISMISSED). Cascades: subscriber-suspend → subs SUSPENDED; terminate → non-terminal subs CANCELLED + entitlements REVOKED + DRAFT invoices VOIDED; sub suspend/cancel/expire → entitlements REVOKED; withdraw → RECORDED pubs AUDIT_FLAGGED; takedown → assets TAKEN_DOWN + all pubs AUDIT_FLAGGED + member-credit debit floored at 0. Every mutation bumps that resource's `version` and refreshes `updated_at`.

**Calculations**: tiered pricing with `Decimal` ROUND_HALF_UP per step (gross = base×bp/10000, discount = gross×pct/100 for members, no post-sum rounding); tier resolution with inclusive min / exclusive max and AMBIGUOUS-before-NO_MATCH precedence; member credit piecewise by word count (2000/5000/9000/14000) + 1500/photo + 4000/video; monthly quota bucket reset (YYYY-MM) with overage billing; invoice overage aggregation over [month_start, next_month_start) excluding DISMISSED; provisional invoice variant ignoring member discount and credit; credit waterfall at issue (min(balance, gross), decrement on application). `months_used_current_period` derived anniversary-style from the logical clock vs. period anchor (start_at / last renewal boundary).

**Validations**: full priority order — auth (401) → role (403) → existence (404, path left-to-right then body FKs) → state (409) → temporal (422) → rights (422) → cross-account (403) → ambiguous/no-match tier (422) → entitlement (422) → min-commitment (422) → fiscal (422); `ERR_VALIDATION` (400) for missing/malformed fields, enums, ranges, pagination params, and duplicate code/slug. Per PRD §3.6, cross-account is checked first among business gates on `POST /wire/publications`; embargo-lift bypasses the temporal republication gate per §3.5.

**OCC**: `expected_subscriber_version` on activate (required, 412 on mismatch, subscriber version +1 on success); `expected_article_version` on republish (same semantics).

**RBAC**: all 7 roles enforced per the §4 endpoint table (endpoint table wins over role-description prose where they conflict, e.g. Legal/SalesOps get 403 on publications/invoices reads); SubscriberRep identity is entity-backed with `ERR_FORBIDDEN_CROSS_ACCOUNT` on foreign resources and auto-scoped publication listing.

**Boot checks**: `bash -n start.sh` OK; `python3 -m py_compile app.py` OK; start.sh executable; live smoke test of 95 assertions passed (93 direct passes; the 2 initial "failures" were arithmetic mistakes in my ad-hoc test's expectations — the server's renewal-notice timing and terminate-cascade-skip-EXPIRED behavior were confirmed correct against the PRD). Server responds within ~2s of invocation and survives per-test reboot with zero carry-over state.

**Orchestrator route-parity check**: normalized (method, path) diff of `app.url_map` vs SCAFFOLD.yaml endpoints = 58/58 exact, missing NONE, extra NONE (placeholder names differ — `{id}` in scaffold vs `{sid}`/`{aid}` in Flask — normalized before comparison).

## Step 7: Run Tests and Iterate — 2026-08-12T10:06:30.000Z

## Summary

- **Iterations run**: 2 (initial sweep identified 4 distinct failing tests; second sweep after fixes passed all 8 rounds cleanly).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/test_suite/test_05_article_pipeline.py` — added missing `create_subscriber` to the `from test_helpers import (...)` list. Three tests (`test_member_credit_cents_piecewise_computation`, `test_member_credit_credited_to_contributor_balance`, `test_takedown_from_withdrawn_applies_same_cascade`) referenced `create_subscriber(...)` without importing it, producing `NameError` at setup. The symbol was already exported by `test_helpers.fixtures` (and re-exported via the barrel's `from .fixtures import *`); the test file just didn't pull it in.

- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/workspace/implementation/app.py` — `suspend_subscriber` now calls `revoke_entitlements_for(sub["id"])` after flipping each `ACTIVE`/`DRAFT` subscription to `SUSPENDED`. PRD §2.9 (line 121) states verbatim: "Suspending, cancelling, or expiring a subscription flips all of its entitlements to `REVOKED`." Combined with PRD §3.2's subscriber-suspend cascade (line 143), the transitive cascade must revoke entitlements; previously only the dedicated `/wire/subscriptions/{id}/suspend` route performed the entitlement revocation, leaving subscriber-level suspensions with orphaned `LIVE` entitlements.

Orchestrator verification: all 8 results files on disk (`results.1.json`–`results.8.json`), each `total=55 passed=55 failed=0 errors=0 skipped=0`, per-test statuses all `passed` — ALL 8 ROUNDS FULLY PASS (55/55 each).

## Step 8: Finalize PRD — 2026-08-12T10:10:05.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/workspace/PRD_FINALIZED.md` is written.

## Exit summary

**Line counts:** PRD.md 283 lines; PRD_FINALIZED.md 283 lines; 0.0% delta (one in-place sentence extension, no lines added or removed).

**Changes (1 total):**
- §3.2 (line 143) — revise — extended the subscriber-suspend cascade sentence to pin the transitive entitlement revocation: every `LIVE` entitlement of each flipped (`ACTIVE` or `DRAFT`) subscription flips to `REVOKED` with `revoked_at` stamped from the current logical clock — `workspace/implementation/app.py:818-832` (the Step 7 fix at line 831, `revoke_entitlements_for(sub["id"])` inside `suspend_subscriber`).

**Step 7 items not patched into the PRD:** the `test_suite/test_05_article_pipeline.py` fix (added missing `create_subscriber` import) is a pure fixture bug — it reveals no PRD silence or impl/PRD mismatch.

**Per-edit pre-edit search log:**
- **Edit 1 (§3.2 suspension cascade):**
  - (a) Subject: entitlement effect of the subscriber-level suspension cascade.
  - (b) Impl paths enumerated/read: `revoke_entitlements_for` (app.py:561-567 — flips only `LIVE` entitlements, stamps `revoked_at` from `CLOCK["current_utc"]`, bumps version); `suspend_subscriber` (app.py:818-832 — Step 7 site; loop covers both `ACTIVE`- and `DRAFT`-origin subscriptions); `suspend_subscription` (app.py:989-1001 — direct route, same helper); `terminate_subscriber` (app.py:859-882 — line 877 also revokes entitlements on the termination cascade; pre-existing, not a Step 7 site); `cancel_subscription` (app.py:1018-1037 — revokes only from `ACTIVE`); `expiry_sweep` (app.py:570-578); `revoke_entitlement` (app.py:1132-1141); `grant_entitlement` (app.py:1072-1092 — no subscription-status check, so `DRAFT` subscriptions can hold `LIVE` entitlements reachable by the cascade); both reinstate routes (app.py:835-843, 1004-1015 — never touch entitlements). PRD prose cross-checked: §2.9 line 121 and line 123, §3.2 line 145, §3.3 line 155, §3.4 line 163.
  - (c) Wording adjustments: scoped the sentence to suspension only (no exclusivity contrast with the termination path at app.py:877); wrote "each flipped subscription" to cover the `DRAFT`-origin branch in the impl loop; mirrored §3.4's "`LIVE` → `REVOKED`, `revoked_at` from the current clock" phrasing so cascade and direct-suspension descriptions stay consistent. §2.9 line 121 left verbatim — with §3.2 now explicit, the combined reading is unambiguous and minimal-change is preserved.

## Step 9: Complete PRD — 2026-08-12T10:21:39.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1253_wire_service_content_syndication_licensing/workspace/PRD_COMPLETED.md` produced as a minimal inline patch over `PRD_FINALIZED.md`.

**Stats**
- Source: PRD_FINALIZED.md, 283 lines / 41,589 chars → PRD_COMPLETED.md, 283 lines / 45,984 chars; char-delta +4,395. 24 paragraphs touched, all in-paragraph inserts/revisions; no new sections or paragraphs.
- Counts: 21 ambiguity-pins, 3 mismatch-revisions (24 total edits).

**Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)**

1. §2.3 — insert — ambiguity — list tie-break: equal `created_at` broken by creation order, earliest first — app.py:362 (`paged` sorts by `(created_at, _seq)`)
2. §2.3 — insert — ambiguity — malformed/out-of-range `limit`/`offset`, out-of-vocabulary enum filters, and non-true/false `is_member` → `ERR_VALIDATION` — app.py:317-357
3. §2.4 — insert — ambiguity — clock adopts supplied instant unconditionally, no monotonicity constraint — app.py:619-626
4. §2.5 — insert — ambiguity — `version` starts at 1 at creation — app.py:217-226
5. §2.8 intro — insert — ambiguity — OCC version comparison evaluated after all applicable ordered checks — app.py:960-977 (activate), 1289-1293 (republish)
6. §2.8 item 7 — revise — mismatch — ordered list ranked cross-account (7) after temporal (5) and rights (6); impl runs it first among business checks on republication — app.py:1396-1399
7. §2.8 final para — insert — ambiguity — uniqueness violations (package/tier/feed `code`, article `slug`) → `ERR_VALIDATION` — app.py:640, 694, 747, 1165
8. §2.8 final para — insert — ambiguity — body required-field/shape checks precede body-FK resolution — app.py:1384-1395
9. §2.8 final para — insert — ambiguity — unsupported method on known path → HTTP 405 with `error_id` `ERR_NOT_FOUND` — app.py:137-144
10. §2.10 — insert — ambiguity — path-parameter validation precedes request-body validation — app.py:891-899, 957-959, 1334-1336, 1540-1544
11. §3.1 packages — insert — ambiguity — `base_monthly_fee_cents` non-negative — app.py:639
12. §3.1 packages — revise — mismatch — retirement lawful only from `ACTIVE` (409 on re-retire); retired package blocks activation but draft subscriptions may still reference it (was "may no longer be referenced by new subscriptions") — app.py:669-677, 899, 966-967
13. §3.1 tiers — insert — ambiguity — `min_audience`/`max_audience`/`circulation_multiplier_basis_points`/`monthly_republish_quota`/`overage_per_article_cents` non-negative — app.py:688-693
14. §3.1 tiers — insert — ambiguity — tier retirement only from `ACTIVE` (409 otherwise) — app.py:726-734
15. §3.1 feeds — insert — ambiguity — `embargo_window_minutes` non-negative; feed born `LIVE` — app.py:746, 754
16. §3.2 — insert — ambiguity — `declared_audience` non-negative; `billing_email` stored as opaque string, no format validation — app.py:782-785
17. §3.2 — insert — ambiguity — termination notice lawful from `ACTIVE`/`SUSPENDED`, 409 from `TERMINATED`, repeated notice re-stamps both timestamps — app.py:846-856
18. §3.3 — insert — ambiguity — draft may be opened under subscriber in any status; `months_used_current_period` derived from clock as whole calendar months since period anchor (`start_at`, then last `renewal_due_at`) — app.py:888-916, 445-449, 192-198
19. §3.3 — insert — ambiguity — activation against non-`ACTIVE` package → `ERR_INVALID_STATE` (HTTP 409) — app.py:966-967
20. §3.3 — insert — ambiguity — renew and send-renewal-notice lawful only from `ACTIVE`; renew moves period anchor to previous `renewal_due_at` and does not clear `renewal_notice_sent_at` — app.py:1040-1066
21. §3.4 — insert — ambiguity — grant consults neither subscription nor feed status; grants not deduplicated — app.py:1072-1092
22. §3.5 — insert — ambiguity — `body_word_count` non-negative — app.py:1157
23. §3.5 — insert — ambiguity — lift-embargo leaves `embargo_until` unchanged — app.py:1255-1265
24. §3.5 — insert — ambiguity — takedown of article with null `member_credit_cents` debits nothing — app.py:1316-1324
25. §3.5 — insert — ambiguity — asset attachment permitted whatever the article's status — app.py:1331-1348
26. §3.6 — revise — mismatch — temporal gate trips only when `embargo_status` is `EMBARGOED` and `embargo_until` is future (was unconditional "`embargo_until` must not lie in the future"); lifted embargo and never-published articles pass — app.py:1400-1407
27. §3.6 — insert — ambiguity — no other article-status precondition at republication; `DRAFT`/`WITHDRAWN` articles may be republished if other gates pass — app.py:1380-1462 (no status check)
28. §3.6 — insert — ambiguity — subscription with no resolved tier records every republication within quota, `billed_amount_cents` zero — app.py:1442-1449
29. §3.6 — insert — ambiguity — `SubscriberRep` publication listing implicitly restricted to own subscriber; explicit foreign `subscriber_id` filter → `ERR_FORBIDDEN_CROSS_ACCOUNT` — app.py:1472-1476
30. §3.7 — insert — ambiguity — `member_credit_applied_cents`/`total_due_cents` null until issuance; for a never-activated subscription `base_fee_cents` and `provisional_total_due_cents` are null at generation — app.py:1551-1572

(Items counted as 24 edits: entries 7–9 were one paragraph edit, 11–12 one paragraph, 13–14 one paragraph, 26–27 adjacent sentences in one paragraph.) Edits 6, 12, and 26 are the three mismatch-revisions; the rest are ambiguity-pins. Everything else in the implementation — endpoint inventory (58 routes match the §4 table exactly, including role sets), envelope shape, pricing/credit/quota formulas, cascade rules, OCC semantics, and state machines — was already uniquely pinned by the PRD and left untouched.
