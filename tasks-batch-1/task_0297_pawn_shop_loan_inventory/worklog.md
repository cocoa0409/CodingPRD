# Worklog — task_0297_pawn_shop_loan_inventory

## Step 1: Create task directory — 2026-06-11T00:00:00.000Z

Created `tasks/task_0297_pawn_shop_loan_inventory/` and `tasks/task_0297_pawn_shop_loan_inventory/workspace/` (pre-assigned index 0297, no scan performed).

## Step 2: Generate scaffold (Expert) — 2026-06-11T00:00:00.000Z

All three scaffold artifacts are generated and validated.

## Task 0297 — Pawn Shop Loan & Inventory (Expert)

Three files written to `tasks/task_0297_pawn_shop_loan_inventory/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

`scaffold_lint.py` verdict: **clean lint** — all 417 §1.8/§1.9 calls conform to §1.5, and all §1.1 FKs have reverse-reachability.

### Scaffold contents
- **Entities (13):** PawnShop, StorageBin, StateRateSchedule, Customer, PawnItem, Loan, FinanceTransaction, InventoryItem, LayawayPlan, LayawayInstallment, PoliceHold, CashDrawer, ClockState
- **State machines (5):** PawnItem, Loan (branching + cyclic extend/renew loop + parallel police-hold dimension), InventoryItem (sell / layaway / reverse-forfeit recall), LayawayPlan (cyclic installment loop), PoliceHold
- **Calculations (8):** loan_amount_from_appraisal, redemption_payoff (+extension_fee/renewal_fee variants), forfeiture_cost_basis, resale_pricing (list vs floor variants), layaway_schedule, layaway_default_refund, drawer_balance, bin_occupancy_overlap (+layaway_reservation_overlap variant)
- **Validations (17):** auth/role/existence/request-shape, segregation-of-duties, police hold, customer-flagged, grace window, period cap, already-serviced, price-below-floor, bin-capacity overlap, layaway-reservation overlap, installment mismatch, principal-non-positive, OCC stale-version
- **Endpoints (45)** · **Error codes (21)** · **Concurrency rules (2)** (OCC on extend & renew)
- **Roles (5):** Appraiser, LoanOfficer, ShopManager, Customer, LawEnforcement (segregation-of-duties model: the appraiser of an item cannot originate its loan)

### Design instance counts
- **Difficulty design (§1.8):** 18 instances — all 9 Difficulty Rules × 2, each cross-domain/different-pair as §0.5 requires.
- **Corner design (§1.9):** 26 active instances + 4 `excluded_because` stubs pointing at §1.8.

All formula-derived assertions were computed in code and pinned as literals (e.g. payoff 22700/25200, cost_basis 25200, list_price 54000, layaway schedule [14426, 14426, 14428], renewal fee 5000, drawer reconciliation 2700/0), and all day-count arithmetic (2026 non-leap) was verified.

## Step 3: Copy INSTRUCTION.md — 2026-06-11T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0297_pawn_shop_loan_inventory/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-11T00:00:00.000Z

PRD generated at `workspace/PRD.md` (298 lines).

**Major sections:**
- §1. Introduction — pawn-shop domain framing (collateralized lending, four-eyes anti-fraud, police-hold compliance, pricing engine, simulated clock).
- §2. Global Specifications — 11 subsections: RBAC (5 roles), Response Structure, Pagination, Common Resource Properties (append-only FinanceTransaction/LayawayInstallment lack updated_at/version), Nested Retrieval & Reverse Reachability, Monetary Precision, OCC on loan servicing, Cash Drawer Ledger & Conservation Invariants, Simulated Clock & Lazy Grace, Police Holds as Cross-Cutting Freeze, Validation Ordering.
- §3. Business Logic & Workflows — 11 subsections by lifecycle.
- §4. Endpoint Definitions — 45 endpoints.
- §5. Error Code Catalogue — 21 error IDs.

**Hard Contract results:** Contract 1 (Field-Name Coverage) PASS (66 names, 0 missing); Contract 2 (Rule Coverage) PASS (both OCC rules, all transitions, all 7 calcs, validation priority, cascades, sibling-branch symmetry, all 21 errors in narrative); Contract 3 (§3 Path Purity) PASS (0 paths/methods in §3).

**Confirmation:** Did not read either withheld design file (SCAFFOLD_DIFFICULTY_DESIGN.yaml / SCAFFOLD_CORNER_DESIGN.yaml).

## Step 5: Generate unit tests — 2026-06-11T00:00:00.000Z

Test infrastructure generation is complete.

**Stage 1 — `test_helpers/` (9 files):** types.py (entity TypedDicts; FinanceTransaction/LayawayInstallment carry only id+created_at), api_client.py (one method per PRD endpoint incl. _clock routes), api_errors.py (all 21 error IDs + HTTP status map), assertions.py, factories.py, constants.py (FL/CA schedules + clock epochs), test_users.py (opaque-role headers + per-operator-id builders for segregation-of-duties), fixtures.py (composite chains: setup_active_loan, setup_forfeited_inventory, setup_layaway_plan, police-hold placers, clock control), __init__.py barrel export. Imports cleanly.

**Stage 2 — `test_suite/` (conftest + 7 test files):**
- 62 test functions, all collect cleanly under pytest.
- Every test carries exactly one Design: tag (62/62, confirmed programmatically).
- Queue A (Difficulty): all 18 instances across 9 rules covered by exactly 2 tests each.
- Queue B (Corner): all 26 non-stub instances covered by ≥1 test. The 4 excluded_because: stubs correctly not translated.
- No unmatched/typo tags; no skip/xfail/skipif; no scaffold/table/§ leakage.

**Instances skipped:** 0. Every instance passed the PRD-first two-condition filter. PRD-citation pass: all 83 quoted PRD sentences survive literal grep of PRD.md (0 missing). Literal expected values copied verbatim from design YAMLs (payoff 22700/25200, per-period 2500, list 54000/floor 25200, layaway 54100 deposit 10820 installments 14426/14428, drawer reconciliations -20000→0 and →2700).

## Step 6: Generate implementation — 2026-06-11T00:00:00.000Z

Implementation complete at `workspace/implementation/`.

**File list (19 files):** start.sh (executable), requirements.txt (flask==3.0.3), app.py (entry, blueprint registration, error handlers, bind-retry loop), db.py (in-memory store + simulated clock epoch 2026-01-01T00:00:00.000Z), errors.py (ApiError + 21 error IDs → HTTP status), response.py (meta/response_type/data envelope, req_ IDs, 3-fractional-digit ISO timestamps), middleware.py (X-User-ID/X-User-Role auth 401 then RBAC 403; 5 roles), helpers.py (pagination limit/offset default 10/min1/max100, field validation, round-half-up, serialization), models.py (record construction, touch() for version/updated_at), services/calc.py (principal-from-LTV, round-per-period-then-multiply payoff, resale pricing, layaway schedule/refund), services/domain.py (lazy grace re-derivation, police-hold lookups, schedule resolution), routes/ (config.py, items.py, loans.py, inventory.py, layaway.py, police.py).

**Endpoints:** 45 distinct method+path endpoints, exact match to PRD §4 table (verified by diff).

**Constraint confirmation:** start.sh reads $PORT (default 10000), binds 0.0.0.0, runs foreground via exec, guards pip install behind .deps_ok sentinel. Storage in-memory only (dicts keyed by id, empty at import) — no SQLite/disk JSON/external persistence; no seeding/preloading. Verified fresh boot returns total_count=0 for all lists, clock at default epoch.

**Smoke validation:** 3 smoke suites (78 assertions, all passing) covering auth/RBAC ordering, CRUD, appraisal+SoD, origination+LTV+bin capacity, payoff fractional rounding, extend/renew/period-cap/OCC, redemption, void+drawer conservation, forfeiture cascade+resale, direct sale below-floor, recall, full layaway lifecycle, layaway cancel+restock refund+cool-down buffer, police hold placement/release/execute.

**Notable PRD-fidelity decision:** For the four loan servicing ops (redeem/extend/renew/forfeit), police-hold/POLICE_HELD freeze is checked BEFORE generic ERR_INVALID_STATE, per PRD §3.6/§3.7/§3.10 which require POLICE_HELD loans surface ERR_POLICE_HOLD_ACTIVE for these ops (POLICE_HELD is itself non-{ACTIVE,IN_GRACE}, so a strict priority-5-first reading would never surface it). Terminal loans without a hold still return ERR_INVALID_STATE.

## Step 7: Run tests and iterate to PASS — 2026-06-11T00:00:00.000Z

All clean. The loop is complete — all 8 parallel rounds pass 62/62 with no flakiness.

**Iterations run:** 2 sweeps (initial diagnostic + post-fix confirmation). Initial sweep showed deterministic (non-flaky) 59/62 in all 8 rounds; second sweep showed 62/62 in all 8 rounds.

**Root cause:** A tension between PRD §2.4 (a lazy ACTIVE→IN_GRACE re-derive counts as a mutation that bumps version) and PRD §2.7 (the OCC expected_loan_version check). On extend/renew, the implementation called rederive_grace first — bumping the loan's version from 1 to 2 — and then compared the client-supplied expected_loan_version (1) against the already-bumped current version (2), spuriously returning ERR_STALE_LOAN_VERSION. Per PRD §2.7, OCC catches "another servicing write," not the request's own passive read-time grace recompute.

**Tests deleted:** None. (No test failed STEP 1 coverage or unique-derivability; the OCC rule and all asserted outcomes are verbatim in PRD §2.7.)

**Fixes applied to implementation/** (routes/loans.py):
- extend_loan — capture occ_baseline_version = loan["version"] before rederive_grace, and compare OCC against that captured baseline instead of the post-re-derive loan["version"]. Fixes test_extension_fee_is_one_period_charge_not_full_payoff.
- renew_loan — same capture-before-rederive fix for the OCC comparison. Fixes test_renewal_resets_baseline_and_increments_count.

**Fixes applied to test_suite/** (test_02_loan_servicing.py, STEP 2 fixture bug):
- test_occ_stale_version_on_renew — the fixture set the clock to DAY_45 after an extend, but the extend pushes term_end_at out to day 60, leaving the loan ACTIVE (not IN_GRACE) at day 45. The renew therefore hit the PRD-mandated state check (§2.11 priority 5) and returned ERR_INVALID_STATE before ever reaching OCC. Changed the clock to GRACE_END (day 60 = the post-extend term_end_at), so the loan re-derives to IN_GRACE, passes the state and period-cap gates, and reaches the OCC check — which correctly returns ERR_STALE_LOAN_VERSION for the stale version. The assertion (exact ERR_STALE_LOAN_VERSION, 412) was preserved unchanged.

No skips/xfails added, no assertions weakened, no PRD-required implementation checks removed, and storage remains in-memory only.

**Note (orchestrator):** Step 7 subagent's final-sweep results.{1..8}.json were cleaned by its own `rm -f` and not left on disk; orchestrator re-ran the 8-round parallel sweep to regenerate durable evidence.

## Step 7 (evidence regeneration) — 2026-06-11T00:00:00.000Z

Orchestrator ran one fresh 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, no `--api-url` — each round claimed a free port via the file-locked registry; `--results-file results.${i}.json` for i=1..8). All 8 rounds reported **passed=62 failed=0 errors=0 total=62** — no flakiness, no ERROR rows, no re-runs needed. results.{1..8}.json left on disk as durable passing evidence. No code, test, or fixture changes made (implementation/, test_suite/, test_helpers/ untouched).

## Step 8: Finalize PRD — 2026-06-11T00:00:00.000Z

The patch is complete. One sentence-group insertion into §2.7, no lines added/removed (the edit lives inside the existing paragraph line 106).

## Summary

**Line counts:** PRD.md = 298 lines, PRD_FINALIZED.md = 298 lines. Net line delta = 0 (the single edit is an inline insertion inside the existing §2.7 paragraph on line 106). Character delta within that paragraph: roughly +780 chars (~0.06% of the document by length; the only changed line).

**Changes (one bullet):**
- §2.7 (OCC on Loan Servicing) — *insert* — pinned that the `expected_loan_version`-vs-`version` comparison uses the loan's `version` as captured at the start of the servicing request, *before* that same request's own lazy ACTIVE→IN_GRACE re-derive; clarified that this request's passive grace recompute (which §2.4 makes a version-bumping mutation) is excluded, while any prior separate write's version advance is still caught — `routes/loans.py:247,266` (extend) and `routes/loans.py:307,334` (renew), backed by `services/domain.py:14-24` (rederive_grace bumps version via `touch`).

**Why this and only this:** The Step 7 diff's sole `implementation/` fix was the `occ_baseline_version = loan["version"]` capture-before-`rederive_grace` change in both `extend_loan` and `renew_loan`. That fix resolves a genuine PRD silence: §2.7's bare "compare against the loan's current `version`," combined with §2.4 (lazy re-derive bumps version) and §2.9 (re-derive fires on touch), leaves it ambiguous whether "current version" means before or after the request's own grace transition. The impl pins "before." The PRD did not uniquely determine this, so it is patched.

**Items deliberately NOT patched:**
- The `test_suite` change (`test_occ_stale_version_on_renew` clock moved to `GRACE_END`) — the Step 7 diff itself classifies this as a STEP 2 fixture bug; the behavior it exercises (renew requires IN_GRACE per §3.5; state-before-OCC per §2.11 priority 5) is already verbatim in the PRD. No silence, no mismatch.
- "Tests deleted: None" — nothing to reconcile.

**Per-edit pre-edit search log (the one edit):**
- (a) **Subject identified:** which `version` baseline the OCC equality check compares against, relative to a servicing request's own lazy ACTIVE→IN_GRACE re-derive.
- (b) **Impl paths enumerated and read/grepped:** grepped `occ_baseline_version | expected_version | expected_loan_version | rederive_grace | touch(loan) | ERR_STALE` across all of `implementation/`. Read and confirmed: `routes/loans.py` extend (lines 240-267) and renew (301-335) — the only two OCC sites, both capture baseline before `rederive_grace`; `services/domain.py:14-24` `rederive_grace` (bumps version only on ACTIVE→IN_GRACE via `touch`); `models.py:37-41` `touch` (version+1 on every mutation); the other `rederive_grace` callsites in `routes/config.py:152,229` and `routes/loans.py:185,197,207` (pure reads/lists — no OCC, unaffected); other `touch(loan)` sites in `routes/police.py:97,155,186` and redeem/forfeit/void in `loans.py` (genuine separate servicing/state writes — these are exactly the "another servicing write" OCC should still catch, and my wording preserves that). Confirmed via `errors.py:32` that `ERR_STALE_LOAN_VERSION` is 412, matching §2.7/§5. Confirmed no other endpoint reads a version field (matches §2.7's last sentence).
- (c) **Wording adjustment to keep all paths consistent:** Added the explicit clause "Any version advance committed by a prior, separate write … is still caught" so the new sentence does not narrow OCC to ignore legitimate concurrent writes (police-hold touch, a prior extend/renew, redeem/void). Scoped the exclusion strictly to "the request's own … grace transition," and acknowledged (citing §2.4) that the re-derive does bump version, so the insertion never contradicts §2.4/§2.9 elsewhere. No path was left mis-described.

## Step 9: Complete PRD — 2026-06-11T00:00:00.000Z

All 7 edits applied cleanly, each an in-paragraph insert/revision, no new sections or paragraphs. Line count unchanged (298→298), char delta +829.

## Summary

**Files:** `PRD_FINALIZED.md` (source) and `PRD_COMPLETED.md` both 298 lines. Char delta: 46,808 → 47,637 (**+829 chars**). All changes are in-paragraph inserts/revisions; no new sections, no new paragraphs, line count unchanged.

**Counts:** 6 ambiguity-pins, 1 mismatch-revision (7 edits total).

**Per-change:**

- **§2.9 (Simulated Clock)** — insert — ambiguity — pinned the fixed clock epoch as `2026-01-01T00:00:00.000Z` (PRD only said "a fixed epoch") — `db.py:14`.
- **§3.5 (Renewal)** — insert — ambiguity — pinned the `RENEWAL_FEE` transaction's `periods_in_charge` to the number of periods due to date (live-period count); PRD was silent on this field for renewal — `routes/loans.py:344`.
- **§3.6 (Redemption)** — insert — ambiguity — pinned the `REDEMPTION_PAYOFF` transaction's `periods_in_charge` to the live-period count it settles (`total_periods` minus prior `periods_charged`); PRD was silent — `routes/loans.py:386`.
- **§3.6 (Void)** — insert — ambiguity — pinned the `VOID_REVERSAL` transaction's `periods_in_charge` to 0; PRD was silent — `routes/loans.py:479`.
- **§3.10 (Execute hold)** — insert — ambiguity — pinned the inventory-item-subject execute path (item → `RECALLED`, its underlying pawn item → `RELEASED_TO_POLICE`), which the PRD described only for a pawn-item subject; also pinned the execute-void `VOID_REVERSAL` `periods_in_charge` of 0 — `routes/police.py:190-198`, `routes/police.py:180`.
- **§3.11 (Clock capability)** — insert — ambiguity — pinned that both the clock-set and clock-read return `data` as a single object carrying just `current_utc` (not a full versioned `ClockState` resource); PRD was silent on response shape — `routes/config.py:247,253`.
- **§4 endpoint table, `GET /pawn/customers/{id}`** — revise — mismatch — added `Customer` to the authorized roles and noted the own-record ownership rule (`X-User-ID` must equal `{id}`, else `ERR_FORBIDDEN_ROLE`). The table omitted `Customer` even though §2.1 prose grants self-reads and the impl allows it — `routes/items.py:49,54-55`.

**Note on a deliberate non-change:** Origination against a shop whose state has no schedule yields `ERR_NOT_FOUND` (`routes/loans.py:85`), an edge the PRD doesn't contemplate (the schedule is not a request-body FK) and that no test exercises. Left untouched to avoid over-specifying an error path the PRD does not admit as an interpretation. Every other impl behavior (auth/RBAC sets, validation ordering, all calculations and rounding sequences, state transitions, bin half-open capacity geometry, layaway cool-down, drawer conservation, list sorting/pagination, response/error envelopes) was already pinned uniquely by the existing PRD prose.
