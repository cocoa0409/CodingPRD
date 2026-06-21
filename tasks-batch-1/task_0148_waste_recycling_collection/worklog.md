# Worklog — task_0148_waste_recycling_collection

## Step 1: Create Task Directory — 2026-06-04T12:18:18.000Z

Created `tasks/task_0148_waste_recycling_collection/workspace/`. Using the pre-specified task path (index not recomputed, per orchestrator instructions). Verified `INSTRUCTION.md` exists at project root for Step 3 copy.

## Step 2: Generate Scaffold — 2026-06-04T12:35:00.000Z

Done. All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with a clean verdict.

### Design (lint-clean, fresh — no sibling tasks consulted)

- **Archetype:** pricing_engine + workflow_orchestration; flat topology; branching/cyclic state shapes; peer-role RBAC (ResidentAccount entity-backed; Dispatcher/Driver/Billing opaque); immediate consistency.
- **12 entities** (ServiceAccount, Cart, ServicePlan, Route, Stop, Pickup, ContaminationTag, WeightTicket, Invoice, SpecialPickup, MissedPickupCredit, DiversionPeriod), **20 errors**, **8 calculations** (12 variant entries), **11 state machines**, **2 OCC concurrency rules**.
- **Expert-band coverage:** entities 12 (10–15), errors 20 (18–30), 3+ calculation variants, 4+ non-linear state machines (Invoice ISSUED↔DISPUTED cycle; SpecialPickup and Pickup branching; Stop bubble-up). Endpoint count is 65 — above the 20–32 guideline, but every endpoint is grounded in a declared state-machine transition or required by the linter's FK reverse-reachability check (f); per documented guidance the lint-driven overage was accepted rather than weakening state-machine completeness or FK reachability.

### Key consistency notes

- `api_prefix` set to `""` so the linter could derive every entity's collection segment from top-level `GET /<entity>/{id}` reads (the canonical fix for the FK_REVERSE_UNREACHABLE wall). All 15 FKs now resolve.
- Quoted 58 `field?` optional tokens inside `input:` flow sequences (unquoted `?` breaks YAML).
- Combinatorial-formula rule spans all three required modes: (a) PAYT marginal tiers, (b) contamination round-per-pickup-then-sum, (c) invoice_total pinned evaluation order.
- All numeric asserts are pre-computed literals (PAYT 1400/5900, contamination 3300, special fees 16000/3500, credits 1500/1750/7000, diversion 50.00, invoice total 6400).
- 19 difficulty instances (≥18, ≥2 per rule), 44 active + 6 stub corner instances, 69 unique names, no forbidden concurrency vocabulary, all `excluded_because` stubs reference real difficulty instances, both OCC write-endpoints declare `expected_*_version` input and bump parent version.

`scaffold_lint.py` final verdict: **clean lint** (514 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-06-04T12:35:14.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-04T12:43:10.000Z

Generated `workspace/PRD.md` (297 lines, 44348 bytes) from SCAFFOLD.yaml. Did not open either withheld design file.

**Document structure:** §1 Introduction (3 paras); §2 nine subsections (RBAC, verbatim §2.2, pagination, common properties, nested retrieval + validation precedence, precision/rounding-order, OCC on stale parents, cascades/bubble-ups/reconciliation, diversion + pay-as-you-throw accounting); §3 eight lifecycle subsections; §4 67-endpoint table; §5 20-error table.

**Key decisions:** §2.2 byte-for-byte; WeightTicket flagged as only `common_fields:false` entity (id + created_at only); both OCC rules in pure stale-version terms (`expected_account_version`/`expected_cart_version`, ERR_STALE_VERSION, 412); two contrasting rounding orders stated explicitly (PAYT sum-then-round vs contamination round-per-line-then-sum); explicit validation precedence chain (auth → role → ownership → path-existence → body-reference → request-shape/pagination → state → OCC → domain).

**Hard Contracts:** Contract 1 (field coverage 56/56) PASS; Contract 2 (rule coverage — validations, OCC, state machines, 7 calculations, 20 error IDs, cascades, sibling-branch symmetry) PASS; Contract 3 (§3 path purity, 438 tokens, 0 paths/methods) PASS.

## Step 5: Generate Unit Tests — 2026-06-04T13:01:40.000Z

Generated test infrastructure (test_helpers/, 8 files) + test cases (test_suite/, 5 files, 82 tests) from the two design indices (design-index-only contract).

### Stage 1 — test_helpers/
- types.py — 13 entity TypedDicts + 15 status/role enums. WeightTicket omits updated_at/version (only common_fields:false entity).
- api_client.py — ApiClient(GenericApiClient), one method per endpoint (all 60+).
- api_errors.py — all 20 error IDs + HTTP-status map via set_error_http_status_map.
- assertions.py, factories.py, constants.py, test_users.py (4 roles; make_resident_headers(account_id) for the lone entity-backed role), fixtures.py (tiered composite setups threading cart OCC version across completions).

### Stage 2 — test_suite/
- Difficulty queue first (all 19 instances, ≥2 tests each), corner queue second (all 44 non-stub instances, ≥1 each). One Design tag per test, verified.

### Coverage (audited)
- 19/19 difficulty instances ≥2 tests (combinatorial_formula carries 3).
- 44/44 non-stub corner instances exactly 1 test each; 6 excluded_because: stubs correctly skipped.
- Every multi-word PRD citation survives whitespace-normalized grep; no ellipses, no skip/xfail. All 82 tests collect cleanly; all api.<method> calls resolve.

### Key adjudication findings (design-vs-PRD inconsistencies handled by honoring verbatim asserted values)
- **payt_weight_charge_marginal_vs_free_allowance**: design's 2nd pickup gross 180 contradicted its own asserted 1400 and prose "net 200 and 150 (total 350)". Set 2nd pickup gross to 200 (→ net 150, total 350 → 1400¢). Added dual-variant test (same 350 lbs → 2900¢ for COMMERCIAL_SMALL, no free allowance).
- **invoice_total_pinned_evaluation_order_mode_c**: design's single TRASH pickup couldn't yield both weight_charge=1400 and contamination=2500. Built self-consistent period: net-200 MAJOR-tagged + net-150 untagged pickups (weight 1400, contam 2500), carrier-fault miss (credit 1500), RECYCLE diverted load (diversion 50.00 vs floor 60 → penalty 1000) → total=6400.
- All arithmetic independently recomputed, matches design literals.

## Step 6: Generate Implementation — 2026-06-04T13:01:40.000Z

Generated Python + Flask implementation in workspace/implementation/.

### What was built
- start.sh — guarded dep install (`if ! python3 -c "import flask"`) then `exec python3 app.py`; binds 0.0.0.0:$PORT (default 10000), foreground.
- app.py — blueprint registration + JSON error handlers; in-memory store empty on every boot (no seeding).
- Foundation: errors.py (20-error catalog), response.py (meta/response_type/data envelope, req_ IDs, ISO-8601 ms UTC), middleware.py (X-User-ID/X-User-Role auth, 4 roles, entity-backed ResidentAccount ownership), db.py (UUID/timestamp/version mgmt; WeightTicket leaner record id+created_at only).
- 9 route modules, all 67 endpoints across 12 entities, full state machines, cascades (account-close → cart retire + plan terminate; route-cancel → stop skip), bubble-ups (pickup → stop), derived-field reconciliation (contaminated, account_balance_cents, total_net_weight_lbs).
- services/calculations.py — Decimal + ROUND_HALF_UP: PAYT marginal tiers (sum-then-round + rate-class free allowance); contamination surcharge (round-per-line-then-sum, highest-severity-dominates); special-pickup fee (BULK flat / HAZARDOUS × hazard multiplier); missed-pickup credit (flat 1500 / 50% special refund); diversion rate (2dp, zero-total→0); diversion penalty (>= floor boundary); invoice total (pinned order, floored at 0).
- services/billing.py — invoice charge over half-open period window, credit absorb/release ledger sync, account-balance recompute (bumps account version per §2.7).

### Key fidelity decisions
- Validation precedence (§2.5): auth → role → ownership → path-existence → body-FK (ERR_REFERENCE_NOT_FOUND) → request-shape → pagination → state → OCC → domain.
- OCC: only the two declared endpoints accept a version field (expected_account_version, expected_cart_version), both → ERR_STALE_VERSION 412, state precondition before OCC.
- ERR_VALIDATION (422) for negative gross weight and size_gallons ∉ {35,65,96}, distinct from ERR_INVALID_REQUEST (400).

### ⚠️ Note for Step 7 (impl-gen flagged): weight-billing and diversion computations key off each WeightTicket.created_at (real server time) falling inside the invoice/diversion [period_start, period_end) window — tests must use windows bracketing "now". Faithful to PRD half-open-window spec, not an impl choice.

## Step 7: Run Tests and Iterate — 2026-06-04T13:01:40.000Z

Clean sweep: zero failures across all 8 parallel rounds.

**Iterations run:** 2 (1 diagnostic baseline sweep that surfaced the failures, 1 confirming sweep after the fix). All 8 parallel rounds now pass 82/82 with a union of 0 failing tests.

**Root cause (single upstream fixture bug, manifested as 10 "independent" failures):** All 10 failures lived in `test_03_billing_charges.py` and all showed weight/diversion/contamination charges computing to 0. Per PRD §3.6 and §3.8, billing replays each `WeightTicket` whose `created_at` (real server time) falls inside the half-open invoice/diversion window `[period_start, period_end)`. The fixtures pinned the window to a hardcoded May 2026 range (`MAY_START="2026-05-01"`, `MAY_END="2026-06-01"`), but the tickets are minted at the actual run time (`2026-06-04`), which is `>= period_end` — so every ticket fell outside the window and all PAYT/diversion/contamination figures collapsed to 0. This is the exact fixture-window bug called out in the implementation-generator hint; the implementation's window semantics are PRD-faithful (verified against PRD lines 176 and 200).

**Tests deleted:** none. All failures traced to a verbatim PRD rule and were uniquely derivable; the defect was in the fixture preconditions, not the assertions.

**Fixes applied to `test_suite/`:**
- `test_03_billing_charges.py` — replaced the hardcoded `MAY_START`/`MAY_END` constants with a `_bracket_now_window()` helper that computes a window from the previous-month start through the next-month start, so the current UTC instant (when tickets are recorded during the run) always falls strictly inside `[period_start, period_end)`. This is STEP 2 (test fixture is the bug), not an implementation change. The window is now date-robust and will keep bracketing "now" on any future run date.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the window-filter semantics in `workspace/implementation/services/billing.py` (`_tickets_in_window`, `period_start <= wt["created_at"] < period_end`) were already PRD-faithful and were left untouched.

## Step 8: Finalize PRD — 2026-06-04T13:01:40.000Z

**PRD_FINALIZED.md created — zero edits.** Byte-identical copy of PRD.md (297 lines, 0% delta).

Step 8 ran because the skip condition requires all four categories at zero; Step 7 had 1 test_suite fix. But that fix was a pure test-fixture bug (the diff's own STEP 2 classification), not a PRD silence or PRD/impl mismatch. All 10 failures were the hardcoded May 2026 billing window not bracketing run-time-minted tickets; the fix replaced it with `_bracket_now_window()`. No implementation change, no test deletion, no test_helpers change.

Verified the impl window semantics are already PRD-faithful at both sites:
- `services/billing.py:17` — `period_start <= wt["created_at"] < period_end` — matches PRD §3.6 line 176 ("half-open invoice window from period_start (inclusive) to period_end (exclusive)").
- `routes/diversion_periods.py:101` — identical condition — matches PRD §3.8 line 200 ("half-open window ... end-exclusive").

No silence to pin, no divergence to correct → no edit warranted under HARD SCOPE.

## Step 9: Complete PRD — 2026-06-04T13:14:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan.

**Source vs completed:** PRD_FINALIZED.md 297 lines / 44,348 chars → PRD_COMPLETED.md 297 lines / 45,067 chars. Char delta +719 (line count unchanged — all in-paragraph inserts/revisions).

**Counts:** 2 ambiguity-pins, 1 mismatch-revision.

**Changes:**
- **§2.1 (RBAC / ownership)** — revise — mismatch — PRD enumerated a closed list of ownership-guarded operations (dispute invoice, request/cancel special pickup) that excluded reads, but impl also enforces `ERR_NOT_RESOURCE_OWNER` on a resident's single-resource reads of Invoice/SpecialPickup/MissedPickupCredit and scopes the three list endpoints to the resident's own resources, while leaving diversion-period reads and account reads unrestricted. Added prose pinning exactly this. — routes/invoices.py:66,78-80; routes/special_pickups.py:61,71-72; routes/credits.py:22,32-33; routes/diversion_periods.py:53-76 (no owner check)
- **§3.1 (ServicePlan create)** — insert — ambiguity — pinned that a non-integer or negative `base_monthly_fee_cents` yields `ERR_INVALID_REQUEST`. — routes/service_plans.py:30-31
- **§3.2 (Stop append)** — insert — ambiguity — pinned that a non-integer or below-1 `sequence` yields `ERR_INVALID_REQUEST` (duplicate case already pinned to ERR_DUPLICATE_SEQUENCE). — routes/routes_bp.py:167-168

**Confirmed already-pinned (no change):** cart size out-of-domain → ERR_VALIDATION; negative gross_weight → ERR_VALIDATION; sum-then-round PAYT vs round-per-line contamination; credit/fee constants; issue-time credit absorption order; invoice resolve re-pricing; lazy-computed account_balance_cents/total_net_weight_lbs. Additive optional query filters beyond endpoint-table summaries left unpinned as additive capability, not contradictions.

## Final Verification — 2026-06-04T13:16:00.000Z

Step 7's per-iteration `rm -f` had cleared the final-sweep `results.{1..8}.json` (known behavior — orchestrator re-runs to regenerate + verify). Re-ran the full 8-round parallel sweep from the orchestrator. **All 8 rounds: passed=82 / total=82 / failed=0; union of failing tests across all rounds = NONE.** Final artifacts `results.{1..8}.json` persisted in `workspace/implementation/`. Pipeline complete.
