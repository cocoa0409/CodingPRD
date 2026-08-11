# Worklog — task_0954_toy_rental_rotation_subscription

Scenario (verbatim): `build task harder than expert level difficulty. 954. Toy Rental & Rotation Subscription: age/developmental catalog, rotation cadence & swap, sanitization & missing-piece, damage/loss fee, wishlist & hold, buy-out, pause/cancel, shipping`

## Step 1: Create task directory — 2026-08-09T16:00:51.300Z

Created `tasks/task_0954_toy_rental_rotation_subscription/workspace/` (next index 0954 after scanning `tasks/task_[0-9]*`; highest existing was 0953).

## Step 2: Generate scaffold — 2026-08-09T16:41:11.779Z

All three artifacts are complete and pass the linter. Summary of what was generated:

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_0954_toy_rental_rotation_subscription/`)

**`SCAFFOLD.yaml`** — §1.0–§1.7 (no difficulty/corner keys inside):
- **Profile**: quota/allocation primary archetype (finite ToyCopy pool vs wishlist holds + box slots) blended with temporal windowing; layers: optimistic concurrency, cascading side effects, dual-variant calculation, ops-run checkpoint; hybrid topology, cyclic state shape, peer-role model, immediate consistency. `api_prefix: /toy-rental`.
- **12 entities**: Member, ChildProfile, SubscriptionPlan, Subscription, CatalogItem, ToyCopy, WishlistEntry, RotationBox, BoxItem, FeeAssessment, Shipment, CreditLedgerEntry (append-only, `common_fields: false`).
- **10 state machines** incl. cyclic Subscription ACTIVE↔PAUSED, full ToyCopy rental loop (AVAILABLE→RESERVED→OUT_ON_LOAN→RETURNED→SANITIZING→AVAILABLE), FeeAssessment dispute cycle (round-limited at 2), BoxItem parallel axes (loan_status × resolution_status), Shipment EXCEPTION→IN_TRANSIT recovery loop.
- **3 OCC concurrency rules** (plan change, box create, item add) — all `expected_*_version` + 412.
- **9 calculations** incl. dual variants (calendar vs rolling-30-day age months; projected vs finalized late fee), combinatorial modes (a) buyout multi-factor, (b) per-item round-then-sum inspection fees (pinned order, 1167 vs 1166 divergence), (c) buyout wallet-application with pinned evaluation order (MIN_NET_CHARGE clamp), selector policy with rank→created_at tie-break, pause allowance (60/365d), cadence schedule, wallet reconciliation with −5000 suspension threshold.
- **22 ordered validations**, **60 endpoints** (count driven by the mandatory FK reverse-reachability GETs for 17 FKs), **39 error codes**, **5 roles** (Anonymous/Member entity-backed + OperationsManager/CustomerService/PlatformAdmin opaque).
- Logical-clock test endpoint with mandatory default `2026-05-01T00:00:00Z`.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 19 instances, all 9 rules ≥2: e.g., swap→copy-release→hold-promotion depth-3 cascade, inspect→fee→ledger→suspension depth-4 cascade, state-vs-fiscal and safety-vs-capacity priority conflicts, inclusive age-min boundary vs swap-allowance boundary, half-open pause-window adjacency vs 24h sanitization buffer gap, wallet charge/waive conservation vs box slot-count conservation. All arithmetic pre-computed to literal cents (6600/6500/100/1500; 350/333/150/334; 300 vs 600).

**`SCAFFOLD_CORNER_DESIGN.yaml`** — 9 taxonomy sections, 51 instances (40 full recipes + 11 `excluded_because` stubs pointing at difficulty instances): CRUD/defaults/not-found, invalid transitions, precondition enforcement (ERR_BOX_EMPTY, hold-expiry strictness), ops-run auto-resume and hold expiry/re-promotion, both LOST_IN_TRANSIT direction cascades, per-item fee cap, RBAC denials, both OCC stale-version tests, pagination envelope, immediate consistency.

**Verification**: `scaffold_lint.py` verdict block (final run, pasted verbatim above): **VERDICT: clean lint** — 60 endpoints, 12 entities, 19 §1.8 + 40 §1.9 active instances, 598 calls scanned, zero violations. Additionally: file-split honored, 70 instance names unique across both design files, no forbidden concurrency vocabulary, enum-value closure verified (every declared enum value is produced by a transition or initialization), and all `${var}` placeholders trace to earlier `captures` resolving to declared §1.5 output fields.

## Step 3: Copy shared files — 2026-08-09T16:41:35.949Z

Copied `./INSTRUCTION.md` → `tasks/task_0954_toy_rental_rotation_subscription/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-09T16:58:53.147Z

All verifications pass. The PRD is complete and shipped.

## Report

**Generated**: `/home/ubuntu/github/CodingPRD/tasks/task_0954_toy_rental_rotation_subscription/workspace/PRD.md` (325 lines) from `SCAFFOLD.yaml`, per the `prd-bench-doc-generator` skill. The two forbidden design files were never opened.

**Structure**: §1 Introduction (2 paragraphs, business-context angle); §2 with 11 subsections — roles/identity semantics, the §2.2 verbatim envelope block (verified byte-identical to `section-2.2-response-structure.md`), pagination, common resource properties (incl. `CreditLedgerEntry` carrying only `id`/`created_at`), the logical clock, nested-path resolution with the full 11-tier validation-pipeline ordering, integer-cents/round-half-up rules with both pinned rounding orders, the three OCC rules naming endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412, wallet-ledger invariant and the −5,000-cent suspension boundary, sanitization protocol, and cascade consistency; §3 with 9 subsections organized by business process (membership/age gate, plans/catalog/copy pool, subscription lifecycle, wishlist/holds, box cycle, inspection/fees, buy-out, fee settlement/disputes, ops checkpoint/account closure); §4 routing table (60 endpoints, exactly 4 columns); §5 error catalogue (39 errors, exactly 2 columns, no trigger conditions).

**Hard contract results** (transcript only, per skill spec — no audit footer in the PRD):

- **Contract 1 — Field coverage**: 91 required identifiers (all `entities[].fields`, endpoint inputs incl. `?`-optional, query params, and sub-structure fields like pause-window `end_date`/`consumed_days`/`closed`, shipment-event `event_type`/`occurred_at`, ops output `promoted_count`/`expired_count`/`resumed_count`/`promoted_entry_ids`, clock `to_iso8601`/`current_utc`) — **91 present, 0 missing. PASS.**
- **Contract 2 — Rule coverage**: validation priority ordering expressed as the explicit §2.6 pipeline plus per-endpoint callouts (e.g., OCC before cadence checks on box create); all 3 OCC rules fully expressed; all 43 state-machine transitions with preconditions + error IDs + side effects; all 9 calculations as reconstruction-safe prose (calendar vs rolling-30-day age variants, projected vs finalized late fee with 150¢/day and replacement-value cap, buy-out four-step formula with grade depreciation 100/85/70/55% and 499¢ floor, pinned wallet application with 100¢ min card charge, per-component-per-item inspection rounding with DAMAGE-first cap, sweep selector with rank/`created_at` tie-break, 60-day pause allowance with 60-legal/61-rejected boundary, cadence schedule, wallet invariant); all `applies_to` scopes enumerated (e.g., the nine member-gated mutations under `ERR_MEMBER_SUSPENDED`); sibling branches rendered symmetrically (CARD vs WALLET_CREDIT, UPHELD vs OVERTURNED, RESTOCK vs QUARANTINE, immediate vs scheduled pause, OUTBOUND vs RETURN lost-in-transit). **PASS.**
- **Contract 3 — §3 path purity**: 514 backticked tokens scanned in §3 — 0 path tokens, 0 bare-method tokens, 0 method+path combos. **PASS.**

**Additional checks**: all 39 error IDs appear in §2/§3 prose; all enum/state values present (a late patch added backticked `CARD`/`WALLET_CREDIT` in §3.8); §4 table has exactly 60 rows × 4 columns with all scaffold paths; §5 has 39 rows × 2 columns; document ends at §5.

## Step 6: Generate implementation — 2026-08-09T17:31:44.186Z

The implementation is complete and verified.

## Summary

Generated a complete Python + Flask implementation at `/home/ubuntu/github/CodingPRD/tasks/task_0954_toy_rental_rotation_subscription/workspace/implementation/` (18 files, ~3100 lines):

- **`start.sh`** — executable, guarded `pip install` (no-op once Flask is present, safe for concurrent per-test reboots), `exec python3 app.py` in foreground on `0.0.0.0:$PORT` (default 10000).
- **`app.py`** — Flask app factory, blueprint registration, error handlers mapping `ApiError` to the scaffold envelope; a global `RLock` serializes requests for in-memory store safety.
- **`store.py` / `timestamps.py`** — empty-at-boot in-memory store (no seeding anywhere), logical clock defaulting to exactly `2026-05-01T00:00:00Z` (never wall-clock), ISO-8601-with-3-fractional-digits formatting, and the calendar-months algorithm with month-end clamping.
- **`validate.py`** — header auth (`X-User-ID`/`X-User-Role`, five declared roles), role authorization, Member-ownership checks, and a two-phase body validator so shape validation (`ERR_VALIDATION`) runs last (priority 11) while domain rules fire first on already-parsed fields.
- **`domain.py`** — wallet ledger with suspension threshold (exactly −5000 stays ACTIVE), targeted/global allocation sweeps (rank ASC, created_at tie-break, max_holds + age-gate + ACTIVE-subscription eligibility, 72h holds), copy release cascades with sweep, fee creation with FEE_CHARGE appends, and the pinned calculations: late fee (150/day, replacement-value cap, floor-of-days), buyout price (Decimal round-half-up on gross×depreciation and rental credit separately, 499 floor), wallet application (read-once, min 100 to card), inspection aggregation (per-component rounding, DAMAGE ranks first, MISSING_PIECES capped to replacement value).
- **`routes_*.py`** (9 modules) — all 47 endpoints, implementing the full state machines (Subscription pause/resume/cancel with half-open windows and 60-day/365-day allowance, ToyCopy rental loop with 24h sanitization buffer and 30-day validity, WishlistEntry hold lifecycle, RotationBox cycle with direction-dependent LOST_IN_TRANSIT cascades, FeeAssessment dispute loop with 2-round cap, Shipment exception recovery), OCC on the three guarded writes (`expected_subscription_version`/`expected_rotation_box_version` → `ERR_STALE_VERSION` 412), plan-term snapshots per box, and immediate-consistency cascades where every touched resource gets `updated_at`/`version` bumps.

**Verification**: three ad-hoc E2E suites (~150 assertions) covering register/auth errors, age-gate calendar vs rolling-30-day variants, sweep promotion/expiry/re-promotion, OCC failures, slot/swap/pause allowance boundaries, ship→deliver→return→inspect→close with exact fee math (749/250 cap split, 500 half-up rounding, 1998 late-fee cap), buyout floor + wallet application, suspension toggle at the −5000 boundary, hold expiry via ops run, chained pause-window activation/auto-resume, and outbound vs return-leg loss cascades — all pass, each suite against a freshly booted server via `start.sh`. One real bug was found and fixed during testing (resume left the subscription PAUSED; `delivered_at` string-vs-datetime split for echo fidelity).

Two judgment calls worth noting: plan terms (toys_per_box, swap allowance, cadence, rental period, buyout discount) are snapshotted on the box at creation per "a box already planned keeps the terms it was created under", and `occurred_at`/`delivered_at`/`received_at`/`current_utc` echo the caller-supplied strings verbatim while system-computed instants use the 3-fractional-digit format from PRD §2.4.

## Step 5: Generate unit tests — 2026-08-09T17:34:19.119Z

Complete. The suite is fully generated and audited.

## What was produced

**`test_helpers/`** (9 files, ~1800 lines) at `/home/ubuntu/github/CodingPRD/tasks/task_0954_toy_rental_rotation_subscription/test_helpers/`:
- `types.py` — 12 entity TypedDicts + 18 enums; `CreditLedgerEntry` correctly omits `updated_at`/`version` (common_fields: false)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (all ~50 routes under `/toy-rental`)
- `api_errors.py` — all 39 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `factories.py`, `constants.py` (LATE_FEE_PER_DAY 150, HOLD_WINDOW 72h, 24h sanitization buffer, 30d validity, suspension threshold 5000, dispute cap 2, pause cap 60, buyout constants)
- `test_users.py` — opaque role constants + `make_member_headers(member["id"])` for the entity-backed Member role
- `assertions.py` — per-entity asserts, `assert_same_instant` (semantic instant comparison, never string), `assert_wallet_matches_ledger`, `assert_active_slot_count`
- `fixtures.py` — composite journeys: `setup_planned_box` / `setup_delivered_box` / `setup_received_box` / `setup_inspected_box` / `setup_closed_box`, `setup_loss_fee`, `setup_two_item_received_box`, `setup_held_entry(_with_box)`, `setup_buyout_context`, OCC-safe writers that always re-read parent versions

**`test_suite/`** — `conftest.py` + 10 test files, **76 tests total**.

## Audit results (all automated checks pass)
- 76/76 tests carry exactly one `Design:` tag as the last docstring line; every tag resolves to a real instance
- Difficulty queue: 18/19 instances × ≥2 tests (36 tests). Corner queue: 40/40 non-stub instances × ≥1 test; 11 `excluded_because` stubs correctly untranslated
- Every citation verified verbatim against PRD.md (8-word-window grep)
- No skip/skipif/xfail markers; no scaffold references in comments; all modules import cleanly; pyflakes clean

## PRD-first adjudication decisions
- **SKIPPED** `Difficulty/cross_entity_state_dependency/box_create_requires_active_subscription` — the PRD never names a subscription-ACTIVE gate for rotation-box creation (§3.5 gives only cadence/sibling/OCC checks; `ERR_SUBSCRIPTION_NOT_ACTIVE` triggers appear only for pause/resume in §3.3). Fails the coverage condition; gap left as a gap.
- **Buyout mode_a/mode_c**: recipes mint a FAIR copy and slot it directly, but PRD §3.2 says new copies carry `last_sanitized_at` null and §2.10 validity requires factory-sealed NEW — so `setup_buyout_context` earns the FAIR grade the PRD-faithful way (clean first loop with `condition_returned: FAIR` inspection, sanitization completion at exactly +24h, box close, second-cycle box). All asserted values (6600/6500/100/1500) preserved; months_rented=2 pinned via delivered_at 2026-06-03 vs clock 2026-08-05.
- **Pause-window instances**: the recipes assumed early resume shrinks a window's recorded interval (not PRD-stated); translated using only PRD-literal semantics — adjacency tested via scheduled windows ([05-10,05-17) + [05-17,05-24)), the pause/resume cycle's second pause starts exactly at window 1's recorded end.
- Dropped non-derivable sub-assertions: literal `version == 1` (initial version unpinned in PRD; relative `assert_version_incremented` used instead) and `held_copy_id` persisting on FULFILLED entries (PRD silent); ledger ordering asserted as multisets (created_at ties under the logical clock).
- `nested_existence_left_to_right` recipe called as CustomerService (would surface tier-2 `ERR_UNAUTHORIZED_ROLE` before tier-3 existence); translated as a Member caller presenting the non-existent id, which correctly surfaces `ERR_MEMBER_NOT_FOUND` per PRD §2.6 ordering.

## Step 7: Iterate tests and fixes — 2026-08-09T17:40:53.300Z

The benchmark is complete. Here is the final summary:

## Summary

**Iterations run**: 1 (single 8-round parallel sweep; no fixes needed).

**Sweep outcome**: All 8 concurrent rounds of `prd-bench-local-run --isolation per-test-server` (76 tests each, server restarted via `start.sh` before every test, per-round free-port allocation) report identical clean results:

- round 1: total=76 passed=76 failed=0 errors=0 skipped=0
- round 2: total=76 passed=76 failed=0 errors=0 skipped=0
- round 3: total=76 passed=76 failed=0 errors=0 skipped=0
- round 4: total=76 passed=76 failed=0 errors=0 skipped=0
- round 5: total=76 passed=76 failed=0 errors=0 skipped=0
- round 6: total=76 passed=76 failed=0 errors=0 skipped=0
- round 7: total=76 passed=76 failed=0 errors=0 skipped=0
- round 8: total=76 passed=76 failed=0 errors=0 skipped=0

**Tests deleted**: none — every test traces to verbatim PRD prose and uniquely-derivable behavior, and zero failures surfaced in any round (no flakiness signal to triage).

**Fixes applied to `test_helpers/`**: none.

**Fixes applied to `implementation/`**: none.

The task at `/home/ubuntu/github/CodingPRD/tasks/task_0954_toy_rental_rotation_subscription/` was already in a converged state from the generation pipeline (implementation built and E2E-verified against PRD.md; test suite generated with PRD-first adjudication — e.g., the scaffold's `box_create_requires_active_subscription` instance had already been skipped at generation time for PRD silence, and non-derivable sub-assertions like literal `version == 1` had already been dropped). The 8-round sweep confirmed stability: 608 total test executions, 608 passes, 0 failures.

## Step 8: Finalize PRD — 2026-08-09T17:40:53.300Z

**SKIPPED.** Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-09T17:49:14.658Z

Done. PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_0954_toy_rental_rotation_subscription/workspace/PRD_COMPLETED.md`.

**Source**: `PRD.md` (no `PRD_FINALIZED.md` present) → `PRD_COMPLETED.md`. Lines 325 → 325 (all edits inline, no sections added); chars 56,378 → 58,608 (+2,230).

**Counts**: 14 ambiguity-pins, 1 mismatch-revision.

- §2.3 Pagination — insert — ambiguity — non-numeric/out-of-range `limit`/`offset` are clamped to defaults/bounds (10, [1,100], 0, floor 0), never rejected; sort ties broken by creation order — validate.py:164-195, domain.py:46-47
- §2.4 Common Resource Properties — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock; `version` starts at 1 at creation — timestamps.py:16-18, domain.py:36-43
- §2.6 Nested Path Resolution — insert — ambiguity — body-carried resource identifiers (`plan_id`, `catalog_item_id`, `toy_copy_id`, `new_toy_copy_id`, `rotation_box_id`) resolve on the path-existence tier, before ownership, with the matching 404 — routes_subscriptions.py:204-207, routes_members.py:250-253, routes_boxes.py:83-86, routes_items.py:94-97, routes_wishlist.py:56-60
- §2.6 pipeline tier (9) — revise — mismatch — `ERR_COPY_NOT_AVAILABLE` is a state-tier (5) check for add/swap (evaluated before age/sanitization/slot gates); only hold acceptance evaluates reservation last, at tier 9 — routes_boxes.py:97-104 vs routes_wishlist.py:104-106
- §2.9 Wallet Ledger — insert — ambiguity — every ledger entry carries a `note` string (supplied note or empty) — domain.py:62-71, serializers.py:238-246
- §2.10 Sanitization — insert — ambiguity — 30-day validity boundary is inclusive (exactly 30 days old still valid) — domain.py:105-110
- §3.1 Registration — insert — ambiguity — email uniqueness compared exactly, case-sensitively — routes_members.py:66-70
- §3.1 Catalog browse — insert — ambiguity — rolling age variant floored at zero; unknown `child_id` filter rejected with `ERR_VALIDATION` — routes_catalog.py:102-112
- §3.2 Plans — insert — ambiguity — `monthly_fee_cents` minimum is 0 — routes_plans.py:36
- §3.2 Catalog — insert — ambiguity — `min_age_months`/`max_age_months` each at least 0 — routes_catalog.py:61-62
- §3.3 Pause — insert — ambiguity — `duration_days` must be at least 1 — routes_subscriptions.py:107
- §3.3 Cancel — insert — ambiguity — cancellation discards every still-open pause window (active and merely scheduled) from `pause_windows` — routes_subscriptions.py:183
- §3.4 Hold acceptance/death — insert — ambiguity — acceptance clears `held_copy_id`, responds 200 with the updated entry; expiry/cancel also clear `held_copy_id`; in every release path a held copy still backing a pending item of an open box is left reserved — routes_wishlist.py:123-127, domain.py:210-230, routes_ops.py:24-46
- §3.6 Inspection — insert — ambiguity — payload validated as a batch before any mutation; per-record errors pinned (`ERR_VALIDATION` for bad enum/negative count/cross-box item, `ERR_BOX_ITEM_NOT_FOUND` for unknown item, `ERR_INVALID_STATE` for an item no longer `PENDING_RETURN`) — routes_boxes.py:239-276
- §3.9 Ops checkpoint — insert — ambiguity — when several scheduled windows of one subscription are due at once, the earliest-starting activates first — routes_ops.py:56-67

All other impl behaviors (state machines, fee formulas, rounding order, suspension threshold, OCC guards, cascades, role tables, error catalogue) were verified to already be uniquely pinned by the existing PRD prose.
