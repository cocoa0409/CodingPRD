# Worklog — task_1658_magazine_publishing_subscription

## Step 1: Create Task Directory — 2026-08-14T05:22:00.000Z

Task directory `tasks/task_1658_magazine_publishing_subscription/` and `workspace/` pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per orchestrator instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T05:51:00.000Z

All three files are in place and the lint passes clean. Here's the summary:

## Summary

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1658_magazine_publishing_subscription/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no scaffold_difficulty_design / scaffold_corner_design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts:**
- Entities: **14** (Publication, Issue, Subscriber, Subscription, SubscriptionTerm, RenewalSeries, RenewalEvent, MailingBatch, MailingLabel, PostalStatement, BackIssueOrder, DigitalEntitlement, DeferredRevenueEntry, CirculationAuditRecord)
- State machines: **7** (Publication, Issue, Subscription, MailingBatch, BackIssueOrder, RenewalEvent, CirculationAuditRecord)
- Endpoints: **100**
- Errors: **38**
- Difficulty instances: **18** (2 per rule × 9 rules — meets §0.5 minimum)
- Corner instances: **29** (25 active + 4 excluded-because stubs)

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design notes:**
- **Primary archetype:** Ledger reconciliation (deferred revenue recognition across subscription lifecycle), secondary workflow orchestration (issue production pipeline with cross-entity gating).
- **Complexity layers:** optimistic_concurrency (3 OCC rules on Subscription/Issue/MailingBatch), cascading_side_effects, dual_variant_calculation, scheduled_deferred_actions (logical clock + GRACE→EXPIRED system transition).
- **Harder-than-expert elements pushed:**
  - Dual-variant deferred revenue (PRO_RATA_ISSUE vs STRAIGHT_LINE_MONTH) with residual absorption rounding order pinned (mode b of combinatorial_formula)
  - Tiered postal rate with 4 inputs and non-linear controlled-surcharge interaction (mode a of combinatorial_formula)
  - paid_percentage_bps uses floor (truncation) — explicitly NOT round_half_up — to trip implementers
  - Boundary: back-issue markup strictly >12 months (12 months = no markup), PERIODICAL paid ratio >= 5000 bps (inclusive), refund tiers at issues_served ∈ {0, 1-3, >3}
  - Depth-3 cascade: Publication suspend → Subscription suspend → RenewalEvent expire
  - OCC on three parents (Subscription, Issue, MailingBatch) with stale-version tests
  - Segregation of duties between FulfillmentManager and PostalComplianceOfficer
- **Test-recipe structure:** every instance has structured `setup_api_calls` + `trigger` with literal payloads and `${var}` placeholders bound to `captures:` from prior calls. All 459 calls validated against §1.5.
- **Endpoint surface:** 100 endpoints including test-driving `POST /_clock/set_current_utc` (default startup time pinned to 2026-08-01T00:00:00Z per skill spec), flat detail GETs for every entity, and `{id}`-placeholder sub-resource GETs satisfying FK reverse-reachability.

## Step 3: Copy Shared Files — 2026-08-14T05:52:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1658_magazine_publishing_subscription/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T06:05:00.000Z

The PRD is generated and all three hard contracts pass. Here is the summary.

## Generation Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1658_magazine_publishing_subscription/workspace/PRD.md` — 379 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications: 2.1 Roles & Access Control · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Nested Resource Retrieval · 2.7 Validation Evaluation Order · 2.8 Monetary Precision and Rounding · 2.9 Optimistic Concurrency Control · 2.10 Deferred Revenue Accounting · 2.11 Postal Compliance and Segregation of Duties
- §3 Business Logic (8 subsections): 3.1 Publications & Issue Pipeline · 3.2 Subscriber File / Subscriptions / Gifts · 3.3 Issue Production · 3.4 Mailing Batches & Postal Verification · 3.5 Mailing Day & Revenue Recognition · 3.6 Suspension/Renewal/Grace/Cancellation · 3.7 Back-Issue Sales & Digital Entitlements · 3.8 Circulation Audits & Wind-Down
- §4 Endpoint Definitions (100-row table, 4 columns) · §5 Error Code Catalogue (49 rows, 2 columns)

## Hard Contract Reports

**Contract 1 — Field-Name Coverage: PASS.** 129 required names (127 entity fields + endpoint request-body/query/path identifiers, deduplicated), all present verbatim in backticks; diff empty (mechanically verified against the scaffold).

**Contract 2 — Rule Coverage: PASS.**
- validations[] priority: 17/17 expressed as an explicit ordered evaluation chain in §2.7, with trigger conditions additionally scattered next to their workflows in §3
- concurrency_rules[]: 3/3 expressed in §2.9 (write action + `expected_subscription_version`/`expected_issue_version`/`expected_batch_version` + exact error ID + HTTP 412; no race-time framing)
- state_machines[].transitions: 31/31 fully expressed (from/to states, preconditions paired with error IDs, all side-effect cascades including publication-suspend, audit-fail, mark-mailed, and cancel cascades)
- calculations[]: 10/10 in precise prose (pro-rata with final-issue residual absorption; straight-line N-month spans incl. WEEKLY÷4-round-up and QUARTERLY×3; full three-class tiered postage table with entry discounts 21/13/7% and 5% Periodical controlled surcharge; gift credit 10% capped at donor deferred balance; truncated basis-points rule; renewal price indexing; 1.5× back-issue markup past 12 months; print-run override floor; three-tier refund 100/90/50% with floor; audit qualification bands 7000/3000 bps inclusive)
- validations[] conditions: 17/17 matchable to their error IDs in §2/§3 prose; all 49 error IDs appear in §1–§3
- endpoints[].side_effects / applies_to: all expressed, including the inventory check applying at both order placement and fulfillment, and the tier/payment consistency check applying at both creation and activation
- entities[].fields[] structured content: all defaults, derived/computed semantics, and the three `common_fields: false` immutable entities (MailingLabel, PostalStatement, DeferredRevenueEntry — no `updated_at`/`version`) reconstructible from prose
- sibling-branch symmetry: all parallel branches (3 postal classes, 3 audit models, 3 refund tiers, 3 renewal-event outcomes, 4 entry points) rendered at equal density

**Contract 3 — §3 Path Purity: PASS.** 487 backticked tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. §2.2 verified byte-identical to the canonical source block.

## Zero-Silence Coverage Audit

Confirmed verbatim coverage for every scaffold entry class: 14/14 entities, 29/29 state values (incl. `CEASED`), all enum field values (`WEEKLY`/`MONTHLY`/`QUARTERLY`, `PAID`/`CONTROLLED`/`MIXED`, both recognition variants, circulation classes, tiers, payment methods, `EXPIRE`/`CONVERT_TO_CONTROLLED`, postal classes/entry points, `PS_3541`/`PS_3541_A`/`PS_3602_R`, access levels, revocation reasons, entry types, qualification results), 10/10 calculations, 17/17 validations, 3/3 OCC rules, 100/100 endpoint paths in §4, 49/49 error IDs in §5 with correct HTTP statuses, 5/5 roles (all `identity: opaque`, individually named in §2.1), and the clock contract (startup default exactly 2026-08-01T00:00:00Z, never wall-clock).

## Adjudication Notes

1. **Inventory boundary (`>` vs `>=`):** the fulfill transition precondition says available inventory must be strictly greater than `quantity`, while validation #12 (applying to both placement and fulfillment) says "at least" the quantity. Followed the validations table (`>=`).
2. **`ERR_DONOR_NOT_FOUND` status:** validation row 7 buckets it under HTTP 422, but the error catalog pins it at 404; used the catalog (404 donor / 422 start-issue), and §5 reflects the catalog statuses.
3. **Cancel refund tiers:** the state-machine side effect sketches a two-tier refund, but `calculations[].refund_on_cancel` defines three tiers (0 served → 100%, 1–3 → 90%, >3 → 50%, floor). Rendered the authoritative three-tier calculation.
4. **Renewal-window sign convention:** the scaffold's offset formula with negative day offsets is arithmetically odd; rendered the semantics (fires when the logical clock crosses the configured pre-expiry offset window; early manual fire → `ERR_RENEWAL_WINDOW_NOT_OPEN`) without pseudocode.
5. **`form_number` mapping / `total_pages`:** scaffold derives the statement form from `postal_class` without giving the mapping, and references an undeclared total-page quantity in `advertising_percentage_bps`; both rendered faithfully without inventing mappings or new fields.
6. **`qualified_subscriber_count`:** transition text and calculation text list partially overlapping condition sets; rendered the union (ACTIVE, deliverable subscriber, start issue no later than this issue's sequence position, issues remaining > 0).

## Step 6: Generate Implementation — 2026-08-14T06:36:00.000Z

Implementation complete. Summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1658_magazine_publishing_subscription/workspace/implementation/`)

- `start.sh` — executable launcher (details below)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, ApiError/404/405/500 envelope handlers, blueprint registration, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — in-memory store: 14 dicts keyed by id, logical clock defaulting to exactly `2026-08-01T00:00:00Z`, global creation-seq counter; `new_record()`/`touch()` (updated_at refresh + version +1). No seeding anywhere — store boots empty.
- `errors.py` — `ApiError` + full 47-entry error catalog with exact HTTP statuses
- `util.py` — ISO-8601 3-fractional-digit timestamps, `req_...` request ids, envelope builders, `limit`/`offset` pagination (default 10, [1,100], offset >= 0 → `ERR_INVALID_PAGINATION_PARAMETERS`), `Decimal`-based round-half-up, field validators
- `auth.py` — `X-User-ID`/`X-User-Role` header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400) and per-endpoint role gating (`ERR_INSUFFICIENT_PERMISSIONS` 403)
- `serializers.py` — explicit output whitelists; ledger resources (MailingLabel, PostalStatement, DeferredRevenueEntry) emit only `id`/`created_at` (no `updated_at`/`version`)
- `services.py` — lookups with left-to-right 404s, issue sequencing, all calculations and cascades
- `routes_pub.py`, `routes_subs.py`, `routes_mail.py`, `routes_orders.py`, `routes_audits.py` — endpoint handlers

## Endpoint count
98 unique route rules covering all 100 scaffold endpoint-table rows (two pairs are the same path with renamed placeholders). Includes the `POST /_clock/set_current_utc` test-driving clock, all nested + flat-alias list endpoints, flat detail GETs, and all lifecycle action endpoints.

## State machines implemented (7)
- **Publication**: ACTIVE → SUSPENDED (pipeline gate `ERR_ISSUE_PIPELINE_ACTIVE`, cascades subs to SUSPENDED + expires PENDING renewal events) → ACTIVE (resume with missed-issue accounting) → CEASED (issues FINALIZED → subs terminal → zero deferred, in that order)
- **Issue**: PLANNING → EDITORIAL_CLOSED → AD_CLOSED ⇄ (reopen blocked once any batch left DRAFT) → AT_PRINTER (print-run computation) → MAILED (serves subs, posts recognition, GRACE/auto-renew-RENEWED, gift entitlements) → FINALIZED
- **Subscription**: PENDING_START → ACTIVE (creates term 1, snapshots variant, adopts default renewal series, sets circulation class) ⇄ SUSPENDED (missed-issue counting on resume) → GRACE → EXPIRED (30-day logical-clock trigger, `CONVERT_TO_CONTROLLED` cyclic regeneration) → RENEWED via renew (OCC, new term, ACCEPTED event, back to ACTIVE) and CANCELLED (refund tier by issues_served: 100%/90%/50% floored, RECOGNITION top-up + REFUND_LIQUIDATION zeroing, entitlement revocation)
- **MailingBatch**: DRAFT → LABELS_GENERATED (OCC, batch inclusion DOMESTIC/FOREIGN/NEWSSTAND, controlled-copy filter, per-label postage) → POSTAL_VERIFIED (PERIODICAL 50% paid / 75% ad limits, STANDARD no-controlled, immutable PostalStatement, PAID-pub <70% audit flag) → TENDERED (mail_date − 1 day gate) → CONFIRMED
- **BackIssueOrder**: PENDING → FULFILLED (FINALIZED + inventory) → SHIPPED → DELIVERED (immediate revenue recognition) → REFUNDED; PENDING → CANCELLED; inventory tracked as buffer − sold with refund restock
- **RenewalEvent**: PENDING → ACCEPTED (on renew) / DECLINED (increments effort counter) / EXPIRED (on next fire, cancel, expiry); manual fire-next with offset-window gate (`ERR_RENEWAL_WINDOW_NOT_OPEN`)
- **CirculationAuditRecord**: DRAFT (one-per-pub, valid period) → FILED (all in-period issues FINALIZED; computes distributions + truncated bps + PAID ≥7000 / CONTROLLED ≤3000 / MIXED band qualification) → AUDIT_PASSED / AUDIT_FAILED (PAID failure cascades publication suspension)

## Calculations implemented (9)
pro-rata per-issue recognition (round-half-up slices, final issue absorbs residual); straight-line-month recognition (span by frequency — WEEKLY ceil(n/4), MONTHLY n, QUARTERLY 3n — floor base + final residual, fired by month-ends crossed on clock set, `recognized_at` = month-end); tiered postal rate (weight tiers per class, entry-point discount bps, PERIODICAL controlled 5% surcharge, round half up only at final multiplication); gift credit (10% half-up, capped at donor deferred, RECOGNITION entry); truncated basis points (0 when empty); renewal offer pricing indexed by effort; back-issue 1.5x markup over 12 months (half-up) + flat shipping (US 500 / foreign 1500 — PRD pins no amounts); print run (qualified count with sequence/deliverability filters, override floor `ERR_PRINT_RUN_TOO_SMALL`); refund tiers with publisher-favorable floor; audit qualification thresholds (inclusive boundaries).

OCC is enforced on exactly the three guarded writes (renew/close-ads/generate-labels, 412s), with the version field required (missing → `ERR_INVALID_REQUEST` at priority 17, after state/temporal checks, matching the PRD's fixed validation order).

## start.sh
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs the server in the foreground via `exec python3 app.py` (signals propagate to Flask). The dependency install is guarded by `python3 -c "import flask"`, so the per-test-server reboots skip pip entirely and boot in under a second. All state is module-level dicts, so every re-invocation starts from a completely empty store — verified by booting via `bash start.sh` and exercising ~140 behavioral assertions across three smoke suites (all passing; the three smoke-script mismatches I hit were wrong expectations in my own test scripts — validation priority ordering and liquidation amounts match the PRD).

## Step 5: Generate Unit Tests — 2026-08-14T06:47:00.000Z

Generation complete and verified. Final summary:

## Test counts

- **Queue A (Difficulty): 34 tests** across 16 translated instances — every translated instance has ≥2 tests (two instances have 3).
- **Queue B (Corner): 29 tests** across 28 translated non-stub instances — every one has ≥1 test (the batch-OCC instance has 2).
- **Total: 63 tests**, collected cleanly by `pytest --collect-only`; zero `skip`/`skipif`/`xfail` markers; zero "scaffold" references in generated code.

## Skipped instances (3, all non-unique-derivability / PRD silence on `piece_weight_oz`)

All three assert exact `postage_cents` values, which depend on each label's `piece_weight_oz`. The PRD never states where `piece_weight_oz` comes from — no endpoint accepts it and §3.4 only says the label "carries the `piece_weight_oz` used for rating." Two PRD-only readers could choose different weights and both be PRD-faithful, so exact postage values are not uniquely derivable:

1. `Difficulty/dual_variant_calc/postal_rate_tiered_vs_controlled_surcharge_divergence` (asserts 32/34 cents at 4.5oz)
2. `Difficulty/combinatorial_formula/postal_rate_tiered_entry_controlled_three_input_nonlinear` (asserts 43/140 cents at 4.5oz)
3. `Corner/calculations/postal_rate_first_class_weight_tiers` (same root cause; its recipe never even creates labels, so the formula is unreachable at chosen weights through the API)

The 4 `excluded_because:` stubs were not translated; all 4 `difficulty_instance` cross-references verified to resolve.

## Files written

- `test_helpers/`: `__init__.py` (barrel), `types.py` (14 TypedDicts; the 3 ledger snapshots omit `updated_at`/`version`), `api_client.py` (one method per unique PRD §4 route, incl. flat aliases), `api_errors.py` (49 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (5 opaque roles), `fixtures.py` (pipeline drivers through FINALIZED, gift/cascade/GRACE/renewal-event scenario builders).
- `test_suite/`: `conftest.py` + `test_01`…`test_11` grouped by concern (registration/listing, subscriptions, lifecycle, issue pipeline, deferred revenue, mailing/postal, publication lifecycle, gifts/cancellation, renewal events, back-issue orders, audits).

## Design adjudications

1. **`renewal_effort_window_half_open`** — the exact half-open boundary (fires exactly on offset day; same-day second fire rejected) is underivable because PRD never defines a subscription's calendar "expiry." Emitted only the two robust arms: fire-next succeeds when the clock (2030) is past any plausible expiry, asserting effort_number 1 / first price 999 / PENDING / denormalized series code; and fire-next 11+ months before any plausible term end → `ERR_RENEWAL_WINDOW_NOT_OPEN`. Boundary-inclusivity sub-claim left as a gap (PRD bug).
2. **`paid_percentage_truncates_not_rounds`** — the recipe's PERIODICAL batch cannot verify (3333 < 5000 bps floor, so no statement is ever written). Substituted a FIRST_CLASS batch (no paid-ratio threshold) with the same 1-paid/2-controlled mix to make floor-vs-round observable on the PostalStatement.
3. **`err_unrecognized_deferred_revenue_blocks_cease`** — PRD §2.7 does not order the cease gates against each other, and the deferred-revenue gate is unreachable in isolation (every terminal subscription has zero deferred balance). Followed the recipe's hedge: issue driven to FINALIZED (neutralizing gate 1), assert `validate_error_is_one_of([ERR_ACTIVE_SUBSCRIPTIONS_REMAIN, ERR_UNRECOGNIZED_DEFERRED_REVENUE])` + 409.
4. **`occ_stale_batch_version_on_generate_labels`** — two tests: pure OCC on a DRAFT batch (`expected = current−1` → 412), and double-generation asserting exactly `ERR_LABELS_ALREADY_GENERATED` (PRD §2.7's explicit fourth-vs-fifth ordering makes the specific state error deterministic; stronger than the recipe's one-of hedge).
5. **`err_stale_subscription_version_on_renew_occ_conflict`** — the recipe's "(simulated)" GRACE was unreachable as written (renew from ACTIVE hits the state check first). Built real GRACE via a 1-issue term + full pipeline + mark-mailed, then renewed with `version−1` → 412.
6. **Auto-fired renewal efforts** (PRD §2.4 "may fire" is permissive): all renewal-event fixtures jump the clock *before* the subscription exists, so the manual fire-next deterministically creates effort 1 under both auto-fire readings.

Automated audit confirmed: every test has exactly one terminal `Design:` tag resolving to a real instance, and every PRD citation survives verbatim containment against `PRD.md` (whitespace-normalized).

## Step 7: Run Tests and Iterate — 2026-08-14T07:05:00.000Z

## Summary

**Result: clean 8-round parallel sweep — all 8 rounds at 63/63 passed, 0 failed, 0 errors.**

### Iterations run
3 sweeps (8 parallel rounds each, 63 tests/round):
- Sweep 1 (baseline): 55/63 in every round — 8 deterministic failures, union size 8.
- Sweep 2: 62/63 in every round — 1 deterministic failure remaining.
- Sweep 3: 63/63 in all 8 rounds — exit condition met.

### Tests deleted
None. Every failing test traced to a verbatim PRD rule with unique derivability; no deletions were warranted.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py` — `list_term_revenue_entries()`: the helper requested the term's DeferredRevenueEntry list without pagination params, so the server applied the PRD §2.3 default `limit=10` and truncated the 12-entry list to 10. This made `test_final_issue_recognition_absorbs_rounding_residual` see only `[100]*10` instead of `[100]*11 + [105]`. Fixed by passing `params={"limit": 100}`. Helper bug, not an implementation bug — the server's pagination behavior was PRD-correct.

### Fixes applied to `implementation/`
- `workspace/implementation/services.py` — `expiry_reference()`: the fallback branch (used when the issue sequence is shorter than the term, so `term_end_issue_id` is unresolved) anchored projected expiry to `term["created_at"]` — the operator-controlled logical-clock instant at activation. That made renewal-effort windows depend on when the clock happened to sit at activation rather than on the subscription's issue-anchored service timeline (PRD §3.2 anchors terms to `term_start_issue_id`/`term_end_issue_id`; PRD §3.6 defines expiry through the grace mechanism, which is driven by issue mailings). Fixed to project from the start issue's `mail_date` (+ frequency-derived span + 30-day grace). This unblocked 7 tests whose fixtures fire renewal efforts at clock 2030 (past any plausible expiry for a 2026 start issue), while `test_fire_next_effort_before_window_open_rejected` (clock 2026-08-01) still correctly yields `ERR_RENEWAL_WINDOW_NOT_OPEN`.
- `workspace/implementation/routes_subs.py` — `cancel_subscription()`: the `REFUND_LIQUIDATION` entry was computed as the negative of the deferred balance *after* the recognition top-up had been applied (−990 for an 1100 balance with a 90% refund). PRD §3.6 pins the entry to "the negative of the **entire** remaining deferred balance" — the same "remaining deferred_balance_cents" the refund is computed from two sentences earlier in the paragraph — i.e., −1100. Fixed by capturing the pre-top-up balance for the liquidation entry (the liability is still zeroed by force-setting `deferred_balance_cents = 0`, and the sibling full-refund test asserting −1205 remains passing).

No implementation checks were weakened, no assertions downgraded, no tests skipped, and no non-PRD behavior was added.

## Step 8: Finalize PRD — 2026-08-14T07:15:00.000Z

Both edits are applied. Line counts are identical (378/378, 0% delta) since both changes are inline revisions within existing paragraphs.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 378 lines → 378 lines, 0% line-count delta; 2 paragraphs revised inline, no sections added or removed.

**Changes (one per Step 7 diff item that warranted a patch):**

- **§3.6 (cancellation paragraph) — revise** — Clarified that the `REFUND_LIQUIDATION` entry's amount is the negative of the same remaining `deferred_balance_cents` the refund was computed from, as it stood *before* the unrefunded remainder's recognition reduced it (i.e., −1100, not the post-top-up −990). The original sentence's placement of "the entire remaining deferred balance" after the recognition clause admitted the post-top-up reading that caused the implementation bug. — `workspace/implementation/routes_subs.py:477-499` (`deferred` captured pre-top-up at :477, `liquidation = -deferred` at :490, liability force-zeroed at :499).

- **§3.6 (renewal paragraph) — revise (insert 4 sentences)** — Pinned the previously undefined "expiry" instant against which effort offset windows are measured: (a) in `GRACE` → grace-entry instant + 30 days; (b) open term's `term_end_issue_id` resolves → that issue's `mail_date` + 30-day grace; (c) issue sequence shorter than the term → start issue's `mail_date` + ceil(`term_issues` × 365 / `issues_per_year`) days + 30-day grace. PRD was silent on this projection entirely (the original implementation anchored it to the operator-controlled `term["created_at"]`). — `workspace/implementation/services.py:584-610` (`expiry_reference`), consumed only by `renewal_window_open` (`services.py:613-617`) from `fire_next_renewal_event` (`routes_subs.py:716-734`).

- **`test_helpers/fixtures.py` pagination fix — no PRD edit.** Pure helper bug (missing `limit=100` param); the server's default `limit=10` truncation was already pinned verbatim by §2.3.

**Per-edit pre-edit search log:**

1. **Edit 1 — REFUND_LIQUIDATION amount basis.**
   (a) Subject: cancellation deferred-balance unwinding / liquidation entry amount.
   (b) Enumerated paths: grep of `REFUND_LIQUIDATION` across all impl files → only `routes_subs.py:486,496` (sole poster); grep of `deferred_balance_cents` → `serializers.py:127` (read-only), `routes_pub.py:228` (cease gate, reads zero-check only), `routes_subs.py:477-499` (edit site), `services.py:274-279` (`apply_recognition`, mailing/gift path), `services.py:426,462` (term creation, gift-credit cap). Also read `post_revenue_entry` (`services.py:258-271`) and both asserting tests (`test_05:231-267` full-refund −1205, `test_08:77-124` partial −1100) to confirm the wording covers both branches (`REFUNDED`/`PARTIALLY_REFUNDED`).
   (c) Wording kept as a parenthetical on the existing sentence so the end-state claim ("zeroes out the liability") still describes the force-set-to-zero outcome without asserting entry arithmetic on the balance; no reference to other sections' balance invariants (§2.10's OPEN-term invariant left untouched, consistent since cancelled terms are not OPEN).

2. **Edit 2 — projected expiry for renewal windows.**
   (a) Subject: the instant "expiry" denotes for effort offset windows.
   (b) Enumerated paths: `services.py:584-610` (`expiry_reference`, all three branches plus two unreachable deeper fallbacks for a missing start issue — deliberately left unpinned since `start_issue_id` is validated at creation and issues are never deleted); `services.py:613-617` (`renewal_window_open`, sole consumer, `now >= expiry + offset`); `routes_subs.py:716-734` (`fire_next_renewal_event`, sole caller, no status guard — so the wording must also cover `RENEWED`/post-renewal subscriptions); `services.py:552-562` (`run_system_transitions` — confirms no auto-fire on clock set, so §2.4's permissive "may fire" stays untouched); `services.py:777-780` (`enter_grace`), `routes_subs.py:444` (renewal resets `_entered_grace_at` to None); `routes_subs.py:755-774` (auto-renew creates the next term without grace entry); series creation validation (`routes_subs.py:597-640`).
   (c) Wording adjustment made: branch (a) phrased as "**While** the subscription is in `GRACE`" rather than "once it has entered GRACE", because a subscription renewed out of grace has its grace timestamp cleared and must fall through to the term/issue-anchored branches — matching the implementation's `_entered_grace_at is not None` check for every post-renewal path enumerated above. The deep fallbacks to `term["created_at"]`/`sub["created_at"]` were intentionally not specified (unreachable via the API; under-determined wording preferred per the no-new-mismatch rule).

## Step 9: Complete PRD — 2026-08-14T07:35:00.000Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1658_magazine_publishing_subscription/workspace/PRD_COMPLETED.md`, sourced from PRD_FINALIZED.md with 30 inline edits (no new sections).

**Size:** PRD_FINALIZED.md 378 lines / 65,279 chars → PRD_COMPLETED.md 380 lines / 70,372 chars (Δ +2 lines, +5,093 chars).

**Counts:** 25 ambiguity-pins, 5 mismatch-revisions.

**Mismatch revisions:**
- §2.4 — revise — mismatch — clock may be set any direction; forward moves fire only grace→EXPIRED and the straight-line month-end pass; renewal efforts never auto-fire (impl fires efforts only via fire-next) — services.py:552-562
- §3.2 — revise — mismatch — dropped "email must be unique per publication"; impl enforces no email uniqueness and subscribers are global — routes_subs.py:79-104
- §3.2 — revise — mismatch — activation adopts the default series code but creates no RenewalEvent (PRD said "first renewal effort is scheduled") — routes_subs.py:354-361
- §3.5 — revise — mismatch — removed the finalization reconciliation gate; impl finalizes any MAILED issue unconditionally — routes_pub.py:525-534
- §3.8 — revise — mismatch — audit distributions are mailed pieces (label count), classified by the recipient's circulation_class at filing time, not "the sum of issues mailed" — routes_audits.py:100-116

**Ambiguity pins (one per change):**
- §2.3 — insert — non-integer limit/offset → ERR_INVALID_PAGINATION_PARAMETERS; creation-timestamp ties broken by creation order — util.py:112-116, db.py:36-41
- §2.5 — insert/revise — `version` starts at 1 at creation; `created_at`/`updated_at` are logical-clock instants — db.py:54-69
- §2.6 — insert — missing term/entitlement/revenue-entry → ERR_SUBSCRIPTION_NOT_FOUND; missing label/statement → ERR_BATCH_NOT_FOUND — services.py:76-84,114-155
- §2.10 — insert — `issue_id` is null on gift-credit, straight-line, and cancellation entries — services.py:258-271,341-343,481-498
- §3.1 — revise — fourth optional issue field `total_pages` (int ≥ 1, default unset); issue creation permitted in any publication status — routes_pub.py:298-353
- §3.2 — revise — every address update recomputes `is_deliverable` both directions; US postal codes must match ZIP/ZIP+4, non-US always valid; only `address_line2` nullable — routes_subs.py:123-147, util.py:218-225
- §3.2 — insert — gift-credit entry carries null `issue_id`, `recognized_at` = current logical clock — services.py:466-473
- §3.2 — revise — issue sequence ordered by `volume_number` then `issue_number`; `term_end_issue_id` null when the sequence doesn't extend — services.py:172-176, 398-410
- §3.4 — insert — batch creation permitted whatever the issue's state; AT_PRINTER gate binds at label generation — routes_mail.py:52-80
- §3.4 — insert — `is_controlled_copy_included` false skips CONTROLLED/COMPLIMENTARY subscriptions at generation — services.py:705-709
- §3.4 — insert — `piece_weight_oz` comes from the generate-labels request, positive number, default 3.0 oz, uniform per batch — routes_mail.py:45,150-152
- §3.4 — revise — pinned form mapping: PERIODICAL→PS_3541, FIRST_CLASS→PS_3541_A, STANDARD→PS_3602_R — services.py:28-32
- §3.4 — revise — `advertising_percentage_bps` = ad_pages_sold×10000/total_pages truncated, zero when `total_pages` unset — routes_mail.py:201-204
- §3.4 — revise — early-warning flag surfaced as the publication's `flagged_for_audit` field — routes_mail.py:236-238
- §3.5 — insert — straight-line pass runs on forward clock-set; months counted from the term's creation month; `recognized_at` = final millisecond of month; null `issue_id` — services.py:316-346, util.py:43-49
- §3.5 — insert — auto-renew term copies current `term_issues`/`price_paid_cents`, starts at the issue after the previous term's end when resolvable, resets service counters — services.py:755-774
- §3.6 — insert — "issues missed" = in-window issues (start issue + term_issues−1 successors) reaching MAILED/FINALIZED during suspension — services.py:485-505
- §3.6 — insert — fire-next with no adopted series or past `max_efforts` → ERR_INVALID_STATE — routes_subs.py:719-727
- §3.6 — revise — `series_code` unique per publication; uniqueness violations → ERR_INVALID_REQUEST — routes_subs.py:619-632
- §3.6 — revise — CONVERT_TO_CONTROLLED regeneration: copies subscriber/publication/start issue/term_issues/series code/expire_action, clears auto_renew and gift fields, opens fresh zero-gross term — services.py:515-549
- §3.6 — revise — renewal: new-term start issue rule, subscription's `term_issues`/`price_paid_cents` updated, `issues_suspended_count` reset, accepted event's `responded_at` stamped, previous term status unchanged — routes_subs.py:429-458
- §3.6 — insert — cancellation entries carry null `issue_id` and current-clock `recognized_at`; full circulation-class recompute rule (live = ACTIVE/SUSPENDED/GRACE; any PAID → PAID_QUALIFIED, else any → CONTROLLED_QUALIFIED, else NON_QUALIFIED) — routes_subs.py:481-499, services.py:212-229
- §3.7 — revise — order placement allowed for an issue in any state; age measured in whole calendar months; shipping 500¢ US / 1500¢ foreign; "copies already sold" = orders in FULFILLED/SHIPPED/DELIVERED — routes_orders.py:32-65, services.py:20-22,232-243
- §3.7 — insert — `is_recognized_revenue` remains true after refund — routes_orders.py:169-180
- §3.7 — insert — revoking an already-revoked entitlement → ERR_INVALID_STATE — routes_subs.py:812-813
- §3.8 — revise — audit-failure cascade suspends the publication only when it still stands ACTIVE — routes_audits.py:166-172
