# Worklog — task_1274_product_placement_brand_integration

## Step 1: Create Task Directory — 2026-08-12T00:00:00.000Z

Pre-assigned output folder `tasks/task_1274_product_placement_brand_integration` with `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-12T01:30:00.000Z

All checks pass. (The `rounding R2: 44` line is an artifact of Python's banker's rounding in my verification snippet; the scaffold pins `round_half_up`, under which 22.5 → 23 per segment and the asserted 46 = 23 + 23 is correct, deliberately diverging from the sum-then-round value 45.)

## Summary

Generated the three scaffold artifacts for task 1274 (Product Placement & Brand Integration) at "harder than expert" calibration, purely from the scenario text plus the skill spec (no sibling tasks consulted).

**Files (all exist, non-trivial):**
- `SCAFFOLD.yaml` — 1603 lines (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 739 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1150 lines (single key `scaffold_corner_design`)

**Scaffold contents:**
- **14 entities**: Brand, BrandBrief, Series, Episode, ScriptOpportunity, IntegrationProposal, IntegrationContract, PropShipment, ContinuityRecord (append-only, `common_fields: false`), CompetitiveClearance, AiringReport, MakeGoodCredit, CrossPromoObligation, DisclosureFiling
- **12 state machines** — cyclic on Proposal (revision rounds), AiringReport (dispute→remeasure loop), PropShipment (reship loop); compound bubble-up on Episode (AIRED→VERIFIED); guarded transitions throughout
- **6 calculations** (dual-variant billing provisional-vs-final, policy-variant clearance score, per-segment rounding order, multi-branch makegood, budget aggregation, cross-promo threshold)
- **24 ordered validations**, **64 endpoints** (incl. `/_clock/set_current_utc` with pinned default 2026-05-01T00:00:00Z), **25 error codes**, **7 roles** (segregation-of-duties: episode creator ≠ production decider; report filer ≠ verifier), **3 OCC concurrency rules** (proposal revision, contract terms, clearance create)
- **Difficulty design**: 9 rules × 2 instances = **18 instances**, all differentiation clauses honored (different entity domains, formula modes a vs b, different triggers/entity pairs/metrics/interval semantics/conserved quantities)
- **Corner design**: **50 instances** (47 active + 3 `excluded_because` stubs) across all nine guide sections

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (837 calls scanned, 0 violations; achieved after adding `GET /series/{id}` for FK segment derivation, removing the unreachable `ERR_DUPLICATE_CONTRACT`, and quoting YAML flow-list edge cases.) All asserted literals were precomputed from the formulas (e.g., provisional 985000, makegood 35000, severity-branch 72000, bonus 10000, per-segment-rounded 46).

## Step 3: Copy Shared Files — 2026-08-12T01:31:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1274_product_placement_brand_integration/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-12T01:50:00.000Z

The PRD is generated and verified. Final summary:

## Generated: `workspace/PRD.md` (306 lines)

### Section list
- **§1 Introduction** — 2 paragraphs (business context + system scope/logical clock framing)
- **§2 Global Specifications** — 2.1 RBAC (all 7 roles with identity translations: `BrandRep` entity-backed by `Brand`, six opaque roles), 2.2 API Response Structure (verbatim fixed block, byte-verified against `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 Common Resource Properties (UUID `id`, 3-fractional-digit timestamps, `version` semantics, `ContinuityRecord` carve-out), 2.5 Logical Clock (initial 2026-05-01T00:00:00Z, no wall-clock fallback), 2.6 Monetary Precision (whole cents, round half-up), 2.7 OCC (all 3 rules), 2.8 Validation Pipeline (12-stage ordered precedence), 2.9 Nested Resources (left-to-right existence)
- **§3 Business Logic** — 8 subsections: brand/brief intake, series/episodes/opportunities, clearance/exclusivity, two-gate proposal negotiation, contract formation/activation/termination, prop logistics/continuity, measurement/verification/settlement, cross-promo/disclosure
- **§4 Endpoint Definitions** — 64-row table (4 columns: Method, Path, Description, Authorized Role(s))
- **§5 Error Code Catalogue** — 25-row table (2 columns), no trigger conditions

### Coverage (all machine-verified)
- **Entities**: all 14 covered (Brand, BrandBrief, Series, Episode, ScriptOpportunity, IntegrationProposal, IntegrationContract, PropShipment, ContinuityRecord, CompetitiveClearance, AiringReport, MakeGoodCredit, CrossPromoObligation, DisclosureFiling); Contract 1 field-name coverage: 78/78 required identifiers present in backticks, 0 missing (two passes)
- **State machines**: all 13 machines fully rendered — every transition's from/to pair, preconditions paired with error IDs, and side effects (including the two-link make-good → cross-promo cascade, the termination → shipment → continuity cascade, and the episode AIRED → VERIFIED bubble-up with its 4 preconditions)
- **Calculations**: all 6 expressed in reconstruction-safe prose — `brief_budget_remaining` (two sums + status sets + release rules), `contract_billing_value` (both provisional and final variants, 1.5 multiplier, quarter-fee bonus cap), `clearance_conflict_score` (40/30 weights, STRICT ≤7-day vs STANDARD <7-day windows, 40/60 deny thresholds), `measured_exposure_valuation` (pinned per-segment round-then-sum with the 46-vs-45-cent worked example), `makegood_compensation` (pinned order, 5000-cent verbal penalty, 0.5 severe ratio, 1.2 surcharge, base-fee cap, reason derivation), `cross_promo_balance`
- **Endpoints**: 64/64 in §4 table including `/_clock/set_current_utc`; all side effects described in §3 narratives; Contract 3 §3 path purity: 447 backtick tokens scanned, 0 path/method violations
- **Validations/errors**: all 25 validation rules expressed with priority ordering stated explicitly (floor-before-ceiling, sanity-before-overlap, lock-before-clearance, etc.); all 25 error IDs appear in §2/§3 prose and in §5 with correct HTTP statuses; all 3 OCC rules name write capability + `expected_*_version` field + `ERR_STALE_VERSION`/412 without time-overlap framing; all 63 enum/state values present verbatim

### Hard contract reports
- Contract 1 (Field-Name Coverage): 78 required, 78 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): 12 validation priority stages, 3 OCC rejections, ~60 state transitions, 6 calculations, 25 validation conditions, all endpoint side effects, field structured content, and sibling branches (production/network decisions, dual billing variants, STRICT/STANDARD policies) all expressed — **PASS**
- Contract 3 (§3 Path Purity): 447 tokens scanned, 0 violations — **PASS**

The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) and sibling task directories were never accessed.

## Step 5: Generate Unit Tests — 2026-08-12T02:05:00.000Z

Generation complete. Summary:

## Deliverables

**`test_helpers/` (9 files)** — `types.py` (15 status enums, role enum, 15 entity TypedDicts; `ContinuityRecord` correctly omits `updated_at`/`version` per PRD §2.4), `api_client.py` (`ApiClient(GenericApiClient)` with one method per PRD §4 endpoint, 52 methods), `api_errors.py` (all 25 error ids + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity shape assertions incl. mutable-vs-append-only common-fields branching, ledger assertion), `factories.py` (input-field-only payload factories), `constants.py` (calculation thresholds), `test_users.py` (shared constants for opaque roles + `make_brand_rep_headers(brand_id)` builder for the entity-backed BrandRep; dual ProductionRep/VerificationAnalyst operators for SoD flows), `fixtures.py` (composite lifecycle fixtures: `setup_approved_proposal` → `setup_pending_contract` → `setup_active_contract` → `setup_aired_contract` → `setup_filed_report` → `setup_verified_report` → `setup_makegood_required` / `setup_settled_contract`, plus clearance/shipment/read helpers).

**`test_suite/` (9 files)** — `conftest.py` + 8 test files, **86 tests total**.

## Coverage audit (both mandatory queues)

- **Queue A (Difficulty): 18/18 instances, exactly 2 tests each = 36 tests.** No difficulty instance skipped — all have verbatim PRD coverage (I rewrote one assertion vs the recipe: the design instance `terminal_state_beats_budget_on_terms_amend` claims `ERR_ALREADY_TERMINAL` for a SETTLED contract, but PRD §2.8's terminal enumeration covers only `TERMINATED` contracts; my two tests assert the uniquely-derivable outcomes — `ERR_INVALID_STATE` for SETTLED and `ERR_ALREADY_TERMINAL` for TERMINATED — preserving the instance's state-beats-fiscal claim).
- **Queue B (Corner): 50/50 non-stub instances, ≥1 test each = 50 tests.** 0 instances skipped. The 3 `excluded_because:` stubs (`provisional_value_at_contract_creation`, `strict_policy_changes_clearance_outcome`, `derived_outstanding_reconciles_after_waive`) were not translated; all three cross-references resolve to real difficulty instances whose tests own those assertions.

## Stage-check verdicts

- **C1 verbatim pass:** 129 quoted PRD segments across 86 docstrings — all survive literal (whitespace-normalized) grep of PRD.md.
- **C4 tag pass:** every test has exactly one `Design:` tag as the final docstring line; 68 unique tags, zero bogus, zero stub-tagged, zero untagged/dual-tagged.
- **Completeness:** difficulty shortfall = none; corner shortfall = none.
- **Lint:** `py_compile` clean on all 18 files; `pytest --collect-only` collects 86 tests with no import errors; static signature check of all helper call sites passes; no `skip`/`skipif`/`xfail` markers; no "scaffold" mentions in generated code; no unused imports.

## Step 6: Generate Implementation — 2026-08-12T02:05:00.000Z

Implementation complete and verified. All work is in `workspace/implementation/`.

## File list (line counts)

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 9 |
| `requirements.txt` (flask>=3.0) | 1 |
| `app.py` (entry point, error handlers, blueprint registration, `0.0.0.0:$PORT`) | 45 |
| `db.py` (in-memory dicts, empty at boot, logical clock default `2026-05-01T00:00:00Z`) | 26 |
| `errors.py` (25 error IDs from the catalog with HTTP statuses) | 76 |
| `response.py` (envelope: `meta.api_request_id/api_request_timestamp`, `response_type`, `data`; pagination fields in `meta`) | 57 |
| `middleware.py` (`X-User-ID`/`X-User-Role` auth, 7-role RBAC) | 44 |
| `util.py` (validation, pagination, timestamps, `touch`) | 162 |
| `routes/brands.py` | 194 |
| `routes/series.py` | 220 |
| `routes/clearances.py` | 128 |
| `routes/proposals.py` | 288 |
| `routes/contracts.py` | 164 |
| `routes/shipments.py` | 150 |
| `routes/airing.py` | 233 |
| `routes/extras.py` (cross-promos, disclosures, clock) | 134 |
| `services/calc.py` (all 6 calculations) | 161 |
| `services/cascade.py` (bubble-up, opportunity release, continuity voiding) | 74 |

## Endpoints: 64 registered vs 64 declared — zero divergence
Verified programmatically: every `(method, path)` pair in SCAFFOLD.yaml §1.5 is registered in Flask, and no extras (Flask's built-in `/static` route was disabled). Orchestrator re-verified independently before sweep: declared=64 registered=64, MISSING none, EXTRA none.

## State machines implemented (13)
Brand (ACTIVE↔SUSPENDED), BrandBrief (DRAFT→OPEN→CLOSED), Episode (SCRIPT_REVIEW→LOCKED→AIRED→VERIFIED with system bubble-up), ScriptOpportunity (IDENTIFIED↔PITCHED→RESERVED→CONSUMED/WITHDRAWN), IntegrationProposal (full two-gate negotiation loop with REVISION_REQUESTED cycle), IntegrationContract (PENDING_SIGNATURE→ACTIVE→UNDER_VERIFICATION→SETTLED/MAKEGOOD_REQUIRED/TERMINATED, plus SETTLED→UNDER_VERIFICATION dispute reopen), PropShipment (9-step lifecycle with reshipment cycle), CompetitiveClearance (REQUESTED→GRANTED/DENIED/RELEASED), AiringReport (FILED→VERIFIED→DISPUTED→RE_MEASURED→VERIFIED cycle), MakeGoodCredit (PENDING→WAIVED), CrossPromoObligation (OWED↔PARTIALLY_FULFILLED→FULFILLED with reverse on makegood cascade), DisclosureFiling (DRAFT→FILED→ACKNOWLEDGED). Terminal states return `ERR_ALREADY_TERMINAL`; other from-state mismatches return `ERR_INVALID_STATE`.

## Calculations implemented (6, with Decimal half-up rounding)
- `brief_budget_remaining` — full recompute over in-flight proposal holds + held contract fees
- `contract_billing_value` provisional variant (script-estimate shortfall × rate × 1.5, subtracted from base)
- `measured_exposure_valuation` — pinned per-segment round-then-sum at 7.5¢/s (verified: [3,3] → 46¢)
- `makegood_compensation` — shortfall × rate × 1.5 + 5000¢/verbal miss, 1.2× severe surcharge at ≥50% shortfall, capped at base fee, COMBINED/EXPOSURE_SHORTFALL/VERBAL_MISS reason
- `clearance_conflict_score` — 40 proximity + 30 watchlist; STRICT window |Δ|≤7 days / threshold 40, STANDARD |Δ|<7 / threshold 60 (verified: STRICT 7-day pair denied with score 40)
- `cross_promo_balance` — OWED/PARTIALLY_FULFILLED/FULFILLED derivation, +1 owed on makegood cascade

## Boot verification (fresh process each time, 3 boots)
- `bash start.sh` boots in ~2s, binds `0.0.0.0:$PORT`, foreground via `exec`
- Logical clock reads `2026-05-01T00:00:00Z` before any clock call (no wall-clock fallback)
- No auth headers → 401 `ERR_UNAUTHENTICATED`; wrong role → 403; SoD checks on production-decision and verify → 403; stale OCC → 412 `ERR_STALE_VERSION`
- Full end-to-end pipeline exercised: brand→brief→submit, series→episode→opportunity, proposal→submit→production-approve→network-approve→contract (provisional computed), clearance GRANT, lock, activate (cross-promo created), disclosure file/acknowledge pre-air, mark-aired after clock advance, report file (ACTIVE→UNDER_VERIFICATION), verify with makegood cascade (MAKEGOOD_REQUIRED, credit + promo owed bump), waive → SETTLED, episode bubble-up → VERIFIED
- `py_compile` passes on all 16 `.py` files; no seeding anywhere — all `db.*` dicts start empty.

## Step 7: Run Tests and Iterate — 2026-08-12T02:20:00.000Z

All 8 rounds pass 86/86. Clean exit.

## Summary

**Iterations run:** 2 sweeps (initial 8-round sweep: 82/86 in every round; post-fix sweep: 86/86 × 8 rounds, zero flakiness).

**Tests deleted:** none — all 4 failures traced to fixable defects; every assertion kept verbatim PRD coverage.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_makegood_required`: replaced the explicit `measured_segments_seconds=[20], measured_verbal_mentions=1` keyword pass-through with `overrides.setdefault(...)` for both. Callers passing those kwargs (e.g., `test_provisional_vs_final_settlement_divergence`) previously caused `TypeError: got multiple values for keyword argument 'measured_segments_seconds'`; defaults still force the documented shortfall scenario when callers omit them.

**Fixes applied to `test_suite/`:**
- `test_suite/test_06_settlement_and_makegood.py` — added missing `setup_active_contract` to the `from test_helpers import (...)` block; `test_makegood_waive_restores_outstanding_balance` and `test_cross_promo_zero_owed_fulfilled_at_creation` referenced it (NameError) while it was only used via the barrel import elsewhere.

**Fixes applied to `implementation/`:**
- `workspace/implementation/util.py` — `now_iso()`: switched from `datetime.now(timezone.utc)` to the logical clock (`db.clock["current_utc"]`, parsed and re-formatted with 3 fractional digits). PRD §2.5 verbatim: "the server must not fall back to wall-clock time at any point" — `test_clock_default_is_fixed_instant` asserts a brand's `created_at` reads the pinned default `2026-05-01T00:00:00Z` before any clock call.
- `workspace/implementation/response.py` — `_now_iso()` (meta `api_request_timestamp`): same wall-clock → logical-clock change for consistency with the same PRD §2.5 sentence; no test depends on the meta timestamp source.

No tests weakened, no skip/xfail added, no PRD-required implementation checks removed, no seeding introduced.

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` files exist on disk; each reports 86/86 passed, 0 failed.

## Step 8: Finalize PRD — 2026-08-12T02:30:00.000Z

Done. `workspace/PRD_FINALIZED.md` is written with exactly one inline insertion.

**Line counts / %-delta:** PRD.md = 306 lines, PRD_FINALIZED.md = 306 lines (0.0% line delta; the edit is one sentence inserted inline into the §2.5 paragraph, +257 characters on line 86).

**Changes (one total):**
- §2.5 (The Logical Clock and Air-Date Semantics) — insert — added "The logical clock is also the source of every server-stamped timestamp: each resource's `created_at` and `updated_at` (§2.4) and the `api_request_timestamp` in the `meta` of every response (§2.2) are all read from the current logical-clock reading." — `workspace/implementation/util.py:8-12` (`now_iso()`), `workspace/implementation/response.py:14-16` (`_now_iso()`).

**Step 7 diff items not resulting in edits (with rationale):**
- `test_helpers/fixtures.py` `setup_makegood_required` — pure fixture bug (duplicate-kwargs `TypeError`); test-side only, reveals no PRD silence about server behavior.
- `test_suite/test_06_settlement_and_makegood.py` import fix — pure test bug (`NameError`); no PRD implication.

**Per-edit pre-edit search log (mandatory for the single edit):**
- (a) Subject: the time source for all server-stamped timestamps (entity `created_at`/`updated_at`; response `meta.api_request_timestamp`).
- (b) Impl paths enumerated and read/grepped: `util.py:8-12` (`now_iso()`, sole timestamp minter, reads `db.clock["current_utc"]` and reformats to 3 fractional digits); `util.py:158-160` (`touch()`, every `updated_at` mutation — 58 `touch(`/`new_entity(` callsites across all routes/services); `util.py:163-165` (`new_entity()`, creation stamps); `routes/shipments.py:122` (ContinuityRecord `created_at` via `util.now_iso()`, no `updated_at`/`version` — matches §2.4 exception); `response.py:19/31/47` (all three envelope builders route `api_request_timestamp` through `util.now_iso()`); `routes/extras.py:126-134` (`set_clock`, sole writer of the clock; echoes stored `current_utc` string); `routes/series.py:61-68` (`air_date` is client-supplied, validated, echoed verbatim — NOT server-stamped); `db.py:26` (initial reading `2026-05-01T00:00:00Z`); grep confirmed `created_at`/`updated_at` are the only `*_at` fields in the codebase.
- (c) Wording adjustment: initial draft said "every timestamp the server emits," which risked a false universal over client-echoed fields (`air_date`) and the `current_utc` clock echo; revised to explicitly name `created_at`, `updated_at`, and `api_request_timestamp` — scoping the claim to exactly the three fields that flow through `util.now_iso()`, consistent with every enumerated path including those Step 7 never exercised (all non-test endpoints' meta timestamps, all entity mutations via `touch()`).

## Step 9: Complete PRD — 2026-08-12T02:50:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as a minimal patch over `PRD_FINALIZED.md`.

**Size:** PRD_FINALIZED.md 306 lines / 51,337 chars → PRD_COMPLETED.md 307 lines / 54,947 chars (**+3,610 chars, +1 line**).

**Counts:** 15 ambiguity-pins, 4 mismatch-revisions (19 edit sites total; all inline insertions/revisions, no new sections).

**Changes:**

- §2.2 Error format — insert — ambiguity — unknown paths / unsupported methods return the standard error envelope with `ERR_NOT_FOUND` (404) — app.py:27-34
- §2.3 Pagination — revise — ambiguity — `offset` ≥ 0, non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` (400); sort tie-break by `id` ascending; `status` filter applied before pagination; `total_count` counts the filtered set; `has_more` = `offset` + returned-items < `total_count`; status param accepted by every list endpoint (no exceptions) — util.py:115-153, response.py:31-44
- §2.4 Common properties — insert — ambiguity — `version` starts at 1; `created_at` == `updated_at` at creation — util.py:163-165
- §2.5 Logical clock — insert — ambiguity — clock-set accepts any parseable ISO 8601 instant (forward or backward); unparseable `to_iso8601` → `ERR_INVALID_REQUEST` (400) — extras.py:126-134
- §2.7 OCC — insert — ambiguity — pipeline placement of the expected-version check: after existence, after state-validity where a from-state requirement exists (revision, terms amendment), before business/temporal/referential/fiscal stages — clearances.py:33-34, proposals.py:199-200, contracts.py:69-70
- §2.8 Validation pipeline — revise — mismatch — stages 3-5 reordered to request-shape → existence → ownership (impl checks ownership only after the resource exists, e.g. brief create/submit/close and report dispute) — brands.py:83-100, 140-179; airing.py:148-161
- §2.8 Validation pipeline — revise — ambiguity — added `VERIFIED` episode to the terminal-state list yielding `ERR_ALREADY_TERMINAL` — series.py:103-104, 119-120, 146-147
- §3.1 Briefs — insert — ambiguity — zero-budget brief submit rejected with `ERR_INVALID_STATE` (409) — brands.py:153-154
- §3.2 Episodes — revise — ambiguity — `episode_number`/`runtime_seconds` are integers; unparseable `air_date` → `ERR_INVALID_REQUEST` (400); naive datetimes read as UTC — series.py:59-62, util.py:15-29
- §3.2 Opportunities — revise — mismatch — the three timecode/exposure fields must be non-negative integers, with negative or non-integer values failing at request-shape (`ERR_INVALID_REQUEST`, 400) rather than `ERR_INVALID_SCENE_WINDOW`; the scene-window check then governs only end ≤ start and end > runtime — series.py:140-153
- §3.3 Clearances — insert — ambiguity — `risk_score` initialized to 0 at request creation — clearances.py:43
- §3.3 Clearances — insert — ambiguity — every grant evaluation, including refused ones, stores `risk_score`, stamps `decided_by_user_id`, and increments `version`; risk-score-threshold refusal reported as `ERR_AIRDATE_PROXIMITY_CONFLICT` (409) — clearances.py:84-108
- §3.4 Proposal submit — revise — mismatch — submission budget ceiling adds the draft's own held `proposed_fee_cents` back before comparison (fails only when remaining budget is negative); pinned episode check error as `ERR_EPISODE_ALREADY_AIRED` — proposals.py:119-122
- §3.4 Proposal decisions — insert — ambiguity — optional `note` accepted but not persisted — proposals.py:129-179 (note never read/stored)
- §3.5 Contract creation — insert — ambiguity — `outstanding_balance_cents` starts at 0 — contracts.py:264
- §3.5 Activation — revise — mismatch — clearance gate matched by `brand_id` (the GRANTED clearance must have been requested for the same brand), not merely the copied category — contracts.py:104-110
- §3.6 Shipment advance — insert — ambiguity — `to` restricted to the seven target states (anything else, incl. `PENDING`, → `ERR_INVALID_REQUEST`); failed contract-ACTIVE prerequisite → `ERR_INVALID_STATE` (409) — shipments.py:13-14, 86, 96-98
- §3.7 Airing-report filing — insert — ambiguity — `contract_id` of a different episode → `ERR_NOT_FOUND` (404); contract not `ACTIVE` → `ERR_INVALID_STATE` / `ERR_ALREADY_TERMINAL` when `TERMINATED`, evaluated after the episode-aired check — airing.py:42-50
- §3.7 Verification/dispute — insert — ambiguity — settlement math runs only when the contract is `UNDER_VERIFICATION` (otherwise report still marked `VERIFIED`, contract untouched); dispute reverses the contract only when it is `SETTLED` (a `MAKEGOOD_REQUIRED` contract is left untouched) — airing.py:114, 164-169

All other implementation behaviors (state machines, calculation formulas and pinned rounding orders, cascade rules, bubble-up triggers, RBAC table, envelope shapes, 201/200 split, left-to-right existence checking, fiscal floor-before-ceiling) were already uniquely pinned by the PRD and left unchanged.
