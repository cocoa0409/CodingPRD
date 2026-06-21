# Worklog — task_0046_public_transit_fare_capping

## Step 1: Create task directory — 2026-05-30T00:00:00Z

Created `tasks/task_0046_public_transit_fare_capping/` with `workspace/` subdir. Index pre-assigned (0046); no auto-scan run per orchestrator instruction (3 sibling pipelines launching concurrently).

## Step 2: Generate scaffold — 2026-05-30T00:00:00Z

All structural invariants hold. The numbers fit the Advanced band (7 entities, 33 endpoints, 14 errors, 4 state machines with branching+cyclic+compound, 3 calculations). Endpoint count is slightly above the Advanced 12-22 guideline because of the mandatory FK reverse-reachability GETs, but that's driven by the flat topology with many peer collections — the entity/calculation coupling is the source of difficulty, not volume.

Final spot check on a numeric assert: the `per_ride_rounding_before_sum` instance (414 vs 413). 275 * 0.5 = 137.5, round_half_up = 138, ×3 = 414. sum-then-round = round(412.5) = 413. Confirmed. And `discount_stacking` 120. And the dual-variant 200 vs 300. All verified.

All three scaffold artifacts are complete and pass the lint cleanly.

### Summary

Generated three scaffold artifacts for **task_0046_public_transit_fare_capping**. All produced fresh from the scenario plus the skill spec — no sibling tasks consulted. `scaffold_lint.py` returns **VERDICT: clean lint** (336 calls scanned, 0 violations, all FK reverse-reachability satisfied).

**Files:**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design` only, 18 instances (9 rules × 2)
- `SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design` only, 28 active instances + 7 `excluded_because` stubs across all 9 guide sections

**Complexity profile:** Ledger reconciliation (primary) + Pricing engine (secondary); flat topology; branching state-machine shape; peer_roles; layers = dual-variant calculation, rate/threshold triggers, derived-field reconciliation, optimistic concurrency.

**Coverage:** 7 entities (FareProduct, Rider, FundingSource, ReducedFareCard, BenefitAllocation, FareWeek, Tap), 33 endpoints, 14 errors, 4 state machines (Tap branching capture/reject + compensating reverse; ReducedFareCard cyclic verify/expire/verify; BenefitAllocation supersede/exhaust; FareWeek open/close), 3 calculations, 5 roles (FareAdmin, Rider [entity_backed], EmployerAdmin, PaymentGateway, Anonymous). One concurrency rule: OCC-on-Rider.version for benefit-allocation create-with-supersede.

**Difficulty-rule design notes (all asserts pre-computed in Python):**
- Rule 1 dual_variant: chronological-actual vs forward-looking quote diverge on an out-of-order tap (300 vs 200, Tap domain); risk score gross vs trailing_week (50 vs 35, Rider domain).
- Rule 2 combinatorial: mode (a) discount stacking takes `max(reduced, low_income)` then `min` over caps (charge 120); mode (b) pinned per-ride round-then-sum (414, not the sum-then-round 413).
- Rule 3 non_linear: Tap fork-join capture/reject + reverse; ReducedFareCard cyclic verify→expire→verify.
- Rule 4 cascade: settle depth-3 (capture → consume benefit → exhaust allocation); reverse depth-2 (credit funds → decrement week), different triggers.
- Rule 5 priority pairs: state-vs-fiscal (WEEK_CLOSED beats INSUFFICIENT_FUNDS); existence-vs-referential (NOT_FOUND beats TAP_WEEK_MISMATCH).
- Rule 6 boundary: exact daily-cap hit charges 0 (settle); transfer-window exact-120-min inclusive (settle).
- Rule 7 cross-entity: Tap→FareWeek (open required); Tap→Rider (active required).
- Rule 8 overlap: transfer sliding-buffer interval vs FareWeek fixed 7-day containment — different interval geometries on different resources.
- Rule 9 invariants: reverse conserves rider out-of-pocket (= FareWeek.charged_total); reverse conserves FSA benefit-consumed cents.

Self-consistency decision: insufficient-funds at settle returns HTTP 402 ERR_INSUFFICIENT_FUNDS **and** persists the Tap as REJECTED (recorded, discoverable via GET), keeping both the branching state machine (Rule 3) and the fiscal error code coherent.

## Step 3: Copy INSTRUCTION.md — 2026-05-30T00:00:00Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-30T00:00:00Z

(First attempt hit a transient 529 Overloaded; retried successfully.)

Generated the PRD at `workspace/PRD.md` (255 lines) from the transit-fare-capping scaffold. Design YAMLs (SCAFFOLD_DIFFICULTY_DESIGN / SCAFFOLD_CORNER_DESIGN) were NOT opened.

**Document shape:**
- §1 Introduction — 3 paragraphs framing ledger-reconciliation + pricing-engine problem.
- §2 Global Specs — 10 subsections: RBAC (5 roles, entity_backed:Rider ownership + 4 opaque identities), fixed §2.2 envelope, pagination, common properties/mutation semantics, integer-cents precision + round-half-up, FareWeek reconciliation invariant, OCC on Rider.version, clock/fare-day/week-window, validation ordering (priorities 1–5), nested left-to-right reference resolution.
- §3 Business Logic — 11 lifecycle subsections scattering all fields/calculations/transitions: fare products, riders + risk score, funding sources, card verify/expire cycle, FSA allocations + supersession, weeks/taps, 4-step chronological settle, benefit selector, forward-looking quote + divergence, reversal compensation, week closing.
- §4 — 33-endpoint table. §5 — 14-error catalogue.

**Hard Contracts — all PASS:** Field-Name Coverage (42/42), Rule Coverage (all state machines, calculations, validations, OCC, side-effects), §3 Path Purity (321 backtick tokens scanned, 0 path/method leaks).

**Correctness fix during generation:** settle funds-branch condition initially written backwards; corrected to capture when `prepaid_balance_cents >= charge_cents`, REJECTED/ERR_INSUFFICIENT_FUNDS when `charge_cents > prepaid_balance_cents`.

## Step 5: Generate unit tests — 2026-05-30T00:00:00Z

Generated complete test infrastructure for `task_0046_public_transit_fare_capping`.

### test_helpers/ (Stage 1 — 9 files)
- `types.py` — 7 entity TypedDicts (all common_fields → id/created_at/updated_at/version) + 8 status/role enums
- `api_client.py` — ApiClient(GenericApiClient), 37 endpoint methods (GET /taps/quote uses query params)
- `api_errors.py` — 14 error IDs + HTTP status map
- `assertions.py` — per-entity assertions + assert_out_of_pocket_conserved / assert_charge_decomposition invariant checkers
- `factories.py` — 7 payload factories (optional/defaulted fields omitted by default)
- `constants.py` — risk-score weights, pagination/discount defaults
- `test_users.py` — opaque headers for FareAdmin/EmployerAdmin/PaymentGateway/Anonymous; make_rider_headers(rider_id) for entity-backed Rider
- `fixtures.py` — atomic blocks + composite worlds (setup_funded_rider, create_captured_tap, getters)
- `__init__.py` — barrel export

### test_suite/ (Stage 2 — conftest + 8 files, 61 tests)
- test_01_crud_and_validation.py (10), test_02_rbac_and_auth.py (3), test_03_state_machines.py (9), test_04_validations.py (10), test_05_pricing_calculations.py (15), test_06_benefit_allocations.py (6), test_07_reconciliation_invariants.py (5), test_08_risk_score.py (2)

### Coverage (design-index-only)
- **Difficulty queue A: 17 of 18 instances translated** (2 tests each = 34 tests).
- **Corner queue B: 27 of 28 non-stub instances translated** (1 test each = 27 tests). All 7 excluded_because stubs left untranslated.
- Zero orphan tags; every test carries exactly one verbatim Design: line; all 87 PRD citations survive literal grep; no skip/xfail; no scaffold leakage.

### Skipped instances (documented gaps)
1. **Difficulty/cross_entity_state_dependency/`tap_settle_requires_rider_active_pair_tap_rider`** — asserts SUSPENDED rider's settle returns ERR_INVALID_STATE, but PRD §3.7 names no error_id for the rider-ACTIVE precondition. Fails unique-derivability.
2. **Corner/validations/`fsa_cap_exceeded_returns_422`** — PRD §3.5 says allocated_cents must not exceed "the regulatory Transit FSA monthly maximum" but never states the numeric ceiling. Fails unique-derivability.

### Design-fidelity adjustment
The branching capture-vs-reject test required transfer_discount_pct: 0 in setup (default free transfer would zero the second ride's charge → CAPTURE not REJECT, contradicting the instance's reject outcome).

## Step 6: Generate implementation — 2026-05-30T00:00:00Z

Generated complete Python + Flask implementation in `workspace/implementation/`. All flows smoke-tested live.

### Files
- start.sh — foreground launcher; installs deps (sentinel-guarded), frees stale $PORT listener, exec python3 app.py on 0.0.0.0:$PORT (default 10000). Boots ~1s.
- app.py — Flask entry, error handlers, 33 routes (/taps/quote registered before /taps/<rid>).
- services.py — pricing engine, benefit selector, settle/reverse side effects, risk score.
- errors.py — 14-error catalog (ERR_INVALID_REQUEST=422, ERR_INSUFFICIENT_FUNDS=402, ERR_STALE_RIDER_VERSION=412).
- db.py (in-memory, starts empty — no seeding), middleware.py (auth/RBAC/ownership), util.py (validation + Decimal round-half-up), pagination.py, response.py (meta/response_type/data envelope), serialize.py, clock.py, requirements.txt (flask==3.0.3).

### State machines
- Tap: PENDING → CAPTURED/REJECTED (REJECTED persisted with unsettled charge_cents, returns HTTP 402) → REVERSED (compensating).
- ReducedFareCard: cyclic PENDING_VERIFICATION/EXPIRED → VERIFIED → EXPIRED → VERIFIED, plus REVOKED.
- BenefitAllocation: ACTIVE → SUPERSEDED (OCC on Rider.version), ACTIVE ↔ EXHAUSTED.
- FareWeek: OPEN → CLOSED (blocked while a PENDING tap references the week).

### Calculations (verified live)
- compute_tap_charge (chronological): discount stacking via max(reduced, low_income), per-ride round-half-up at each pct mult, transfer discount within transfer_window_minutes (boundary inclusive), daily-then-weekly cap credit from prior CAPTURED taps, then FSA benefit after caps.
- compute_quote (forward-looking): appends hypothetical tap to today's captured set, diverges from chronological on out-of-order taps.
- benefit_selector: ACTIVE allocations for fare-day month with headroom, ranked remaining-cents DESC, created_at ASC tiebreak.
- rider_risk_score: 15·rejects + 8·reversals + 20·low-balance, clamped to 100; gross vs trailing_week (7-day).
- Reconciliation invariant: FareWeek.charged_total_cents and funding-source balance conserved across reversal.

### Notes
- MONTHLY_FSA_CAP_CENTS = 32500 (IRS qualified-transit monthly limit; PRD says only "regulatory Transit FSA monthly maximum").
- Duplicate-vs-supersede path collapses onto the OCC check; ERR_DUPLICATE_ALLOCATION effectively subsumed, matching PRD prose.

## Step 7: Test + fix loop — 2026-05-30T00:00:00Z

All 8 parallel rounds pass cleanly (60/60 each).

**Iterations run:** 2 sweeps (initial baseline + 1 fix iteration). Final sweep: all 8 parallel rounds green at 60/60.

The initial sweep showed 60 of 61 tests failing identically across all 8 rounds — a systematic setup error, not flakiness. Two root causes, then two residual failures, all traced to test-side bugs (plus one unconstructible-scenario deletion). No implementation code was changed.

**Tests deleted (1):**
- `test_closed_week_beats_insufficient_funds` (`test_04_validations.py`) — STEP 1b unique-derivability collapse (unconstructible precondition / error-precedence silence). The test recorded a PENDING tap, then expected `close_fare_week` to succeed (HTTP 200) before settling against the closed week to assert `ERR_WEEK_CLOSED` beats `ERR_INSUFFICIENT_FUNDS`. PRD §3.11 states verbatim: "Closing is permitted only when no tap in `PENDING` status references the week; any pending tap must first be settled or the close is refused." Since settle is defined only out of `PENDING` (§3.7), a settleable tap can never coexist with a CLOSED week — the asserted precedence is unconstructible under any PRD-faithful implementation, which correctly refuses the close with `ERR_INVALID_STATE`. Scaffold rule that drove generation: `Difficulty/priority_pair_validation_conflict/closed_week_beats_insufficient_funds_state_vs_fiscal`. (The OPEN-week control `test_settle_open_week_underfunded_returns_insufficient_funds` was kept; a code comment documents the deletion.)

**Fixes applied to test_helpers/ (2 files):**
- `factories.py` — changed `DEFAULTS["ZONE"]` from `"ZONE_X"` to `"ZONEX"`. PRD §3.1 declares `zone_code` "an uppercase alphanumeric identifier"; the underscore violated the precondition, and the PRD-faithful implementation correctly rejected every product create with `ERR_INVALID_REQUEST`, cascading into ~54 setup failures.
- `fixtures.py` — (a) updated `ZONE_X` defaults to `ZONEX` in `open_week`, `setup_funded_rider`, `setup_world_with_captured_tap`; (b) fixed `setup_funded_rider` to merge `zone_code` into `product_overrides` (`prod_kwargs = {"zone_code": zone_code}; prod_kwargs.update(...)`) instead of passing it both positionally and via `**product_overrides`, eliminating the `TypeError: make_fare_product() got multiple values for keyword argument 'zone_code'` that broke ~7 pricing tests.

**Fixes applied to test_suite/ (2 files):**
- All test files — replaced every underscore-bearing setup zone code (`ZONE_X/Y/Z/W/A/R` → `ZONEX/Y/Z/W/A/R`) to satisfy the PRD's uppercase-alphanumeric rule. No test asserted zone-format rejection, so these were purely accidental invalid-precondition values.
- `test_06_benefit_allocations.py::test_supersede_with_stale_version_returns_412` — STEP 2 fixture-faithfulness fix. The test assumed the first allocation create advanced the rider's `version`, but PRD §2.7/§3.5 increment the rider version only on a *supersede*; an initial create (no prior ACTIVE allocation) does not, so the presented version was never actually stale and the implementation correctly succeeded. Rewrote the setup to perform a genuine first supersede (advancing rider version), then present the now-stale version on a second supersede — matching the PRD's "two strictly sequential [supersede] creates ... cannot both succeed" scenario and correctly exercising the `ERR_STALE_RIDER_VERSION` (412) branch.

**Fixes applied to implementation/:** None. The implementation was PRD-faithful throughout; every failure was a test-side precondition or setup bug.

## Step 8: Finalize PRD — 2026-05-30T00:00:00Z

`PRD_FINALIZED.md` produced. After tracing each `<step_7_diff>` item to its behavior in `implementation/`, **no PRD edits were warranted** — every diff item is a pure test/fixture artifact whose behavior the PRD already uniquely determines. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (255 lines, 0 delta; confirmed identical via diff).

**Per-item disposition (why no edit):**
1. Deleted `test_closed_week_beats_insufficient_funds` — Not a PRD silence. PRD §3.11 (close requires no PENDING tap) + §3.7 (settle only out of PENDING) make the asserted precedence unconstructible. Impl close-guard + settle fully PRD-determined.
2. `factories.py` ZONE_X → ZONEX — Pure fixture bug. PRD §3.1 already declares zone_code "an uppercase alphanumeric identifier"; impl enforces `^[A-Z0-9]+$`.
3. test_suite underscore zone codes — Same as item 2; PRD-determined.
4. `test_supersede_with_stale_version_returns_412` rewrite — Not a PRD silence. PRD §2.7/§3.5 pin that version increments only on supersede; an initial create does not. Impl `touch(rider)` only in supersede branch.

**Pre-edit search log (mandatory enumeration):** subject = Rider.version mutation; grepped impl for touch(rider)/rider["version"]; found rider mutated in exactly two places (suspend_rider, pinned by §3.2; supersede branch of create_benefit_allocation, pinned by §2.7/§3.5); plain-create path never touches rider. All rider-version behavior already PRD-determined. No wording adjustment (no edit).

## Step 9: Complete PRD — 2026-05-30T00:00:00Z

`PRD_COMPLETED.md` produced. Full PRD-vs-implementation scan.

**Source vs output:** `PRD_FINALIZED.md` (255 lines, 39,950 chars) → `PRD_COMPLETED.md` (255 lines, 40,236 chars). Char-delta: +286; line-delta: 0 (both edits in-paragraph on §3.5, line 156).

**Counts:** ambiguity-pins: 1; mismatch-revisions: 1.

**Changes:**
- §3.5 (Transit FSA Benefit Allocations) — insert — ambiguity — PRD said allocated_cents "must not exceed the regulatory Transit FSA monthly maximum" but never gave the numeric ceiling; pinned to 32500 cents, rejection on amounts strictly above — `services.py:19` (MONTHLY_FSA_CAP_CENTS = 32500), `app.py:471-472`.
- §3.5 — revise — mismatch — PRD claimed a duplicate-active-allocation create not satisfying supersede preconditions is rejected with `ERR_DUPLICATE_ALLOCATION` (409), but impl never emits it: `expected_rider_version` is mandatory (missing/non-int → ERR_INVALID_REQUEST), and when an active allocation exists the create unconditionally takes the supersede/OCC path (mismatch → ERR_STALE_RIDER_VERSION 412). Revised prose to describe always-supersede behavior; ERR_DUPLICATE_ALLOCATION row left in §5 catalogue as defined vocabulary — `app.py:461-495`.

**Other findings (verified consistent — no change):** discount stacking (max never sum), per-ride round-half-up, chronological vs forward-looking quote divergence, daily/weekly cap rooms, transfer-window inclusive boundary, benefit selector ordering, risk-score weights/modes/clamp, card verify/expire/revoke cycle, fare-week 7-day window + zone match, settle capture/reject branch + reverse compensation, response envelope + pagination, validation-priority ladder — all already uniquely match impl.

## Pipeline complete — final verification — 2026-05-30T00:00:00Z

Step 7's subagent did not leave its passing `results.*.json` behind, so the orchestrator re-ran the 8-round parallel stability sweep (implementation unchanged since Step 7). **All 8 rounds green: 60/60 passed, 0 failed.** `results.{1..8}.json` regenerated under `workspace/implementation/` as durable evidence.

Final artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 8 test files, 60 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (identical to PRD.md), PRD_COMPLETED.md (+2 §3.5 edits), implementation/ (12 source files + start.sh + results.1-8.json)}.
