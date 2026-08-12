# Worklog — task_1211_marine_salvage_wreck_removal

## Step 1: Create Task Directory — 2026-08-11T22:06:05.801Z

Pre-assigned output folder `tasks/task_1211_marine_salvage_wreck_removal` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; treating Step 1 as done.

## Step 2: Generate Scaffold — 2026-08-11T23:07:55.990Z

Done. The three scaffold artifacts are written and the linter passes clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    86
  §1.1 entities declared:     16
  §1.8 instances scanned:     19
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1225

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Output files

- `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/SCAFFOLD.yaml` — §1.0–§1.7 only (16 entities, 14 state machines + 2 OCC concurrency rules, 11 calculations, 12-priority validation stack, 86 endpoints, 39 error codes, 7 opaque roles)
- `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` with 19 instances (every §0.5 rule ≥2; combinatorial_formula carries 3, one per mode (a)/(b)/(c))
- `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` with 62 active instances + 2 `excluded_because:` stubs across entities/state_machines/calculations/validations/endpoints/rbac/cross_cutting_layers/consistency_model

## How "harder than expert" was passed through

- **Archetype blend**: compliance/audit (segregation-of-duties role model, insurer doc-pack completeness gate, permit agency coordination) × multi-party negotiation (OFFERED⇄COUNTERED OCC-guarded cycle, arbitration with appeal loop)
- **Rule differentiation highlights**: dual variants on *different domains* (award money 96,000,000 provisional vs 75,000,000 final; pollution exposure tariff 25,000,000 vs actual 24,000,000); combinatorial formulas in three distinct modes (tiered+conditional Article-13 enhancement; per-line rounding pinned at 12,500,014 vs the non-conformant 12,500,013; SCOPIC netting with pinned evaluation order → payable collapses to 0); depth-3 cascade (pollution escalate → env_posture → phase ENV_SUSPENDED → charter STANDBY_ENV) vs depth-2 bubble (final phase complete → contract PERFORMANCE_COMPLETE → casualty OPERATIONS_COMPLETE); two OCC rules (contract counter, assessment supersede); two interval semantics (charter half-open adjacency-allowed vs storage-site aggregate capacity); money and mass conservation invariants
- Every numeric assert was pre-computed by hand-simulating the formulas (e.g., tier-straddle award 54,240,000; demurrage strict-boundary 23,000,000; overrun threshold exactly at 110% stays false at 11,000,000, flips at 12,000,000)
- Logical clock endpoint with the mandated `2026-05-01T00:00:00Z` default drives permit/weather-window expiry sweeps deterministically

Auxiliary checks beyond lint also pass: placeholder closure (every `${var}` bound by an earlier `captures:`), 83 globally unique instance names, all 39 error codes triggerable by at least one instance, enum closure, and no forbidden concurrency vocabulary. Note: the task directory already contained a `worklog.md` and `workspace/` (pre-existing, timestamps predate my writes); per the no-peek constraint I did not read them and left them untouched.

## Step 3: Copy Shared Files — 2026-08-11T23:08:16.615Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1211_marine_salvage_wreck_removal/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T23:25:38.542Z

PRD generation is complete and verified.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/workspace/PRD.md` (349 lines)

**Document structure** (domain-derived, not template-copied):
- §1 Introduction — 2 paragraphs (business context + operating model)
- §2 Global Specifications — 10 subsections: RBAC (7 roles, opaque identities, actor-field SoD), API Response Structure (§2.2 emitted byte-verbatim from the canonical source), Pagination (limit 10 default / 1 min / 100 max, offset 0, `created_at` ascending), Logical Clock & Sweeps (default 2026-05-01T00:00:00Z, permit/window expiry), Common Resource Properties (UUID id, ISO 8601 with 3 fractional digits, version semantics, DocEntry exception, null-until-event fields), Money/Mass Conservation Invariants, Validation Pipeline priority 0–11 (incl. safety-before-fiscal at activation and terminal-state precedence at the priority-5 tier), Nested Resource Validation (left-to-right), OCC, and Cascade taxonomy (A/B/termination)
- §3 Business Logic — 9 subsections following the business timeline (intake → planning → negotiation → security/activation → permits → equipment/weather/operations → pollution/SCOPIC → property/liens → award/settlement/docs)
- §4 Endpoint table — 86 rows, 4 columns only
- §5 Error catalogue — 39 errors, 2 columns only, statuses matching the scaffold (409s for overlap/capacity/duplicates, 412s for OCC, etc.)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 119 entries, 96 unique required, 96 present, 0 missing
- endpoints[].request_body/input: 140 entries, 68 unique required, 68 present, 0 missing
- endpoints[].path_params: 16 required, 16 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (ordered pipeline §2.7), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write action + expected_*_version + error_id + 412), 0 missing
- state_machines[].transitions: 86 checked across 16 state machines, 86 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose (all constants embedded), 0 missing
- validations[] conditions: 13 entries / 39 error ids, all matchable to prose triggers, 0 missing
- endpoints[].side_effects / applies_to: 86 checked, 86 expressed, 0 missing
- entities[].fields[] structured content: 119 checked, 119 reconstructible (defaults, null-until, init values), 0 missing
- sibling-branch symmetry: 12 groups checked, 12 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 262 unique
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: all state/enum values present verbatim, no fuzzy words or pseudocode operators in prose, all 39 error IDs appear in §2/§3, §2.2 placeholders intact, and the document ends at §5 with no audit footer. The two withheld design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-11T23:57:40.477Z

All generation and audits are complete. Final report:

## Generated

**`/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/test_helpers/`** (Stage 1)
- `types.py` — 30+ enums and 16 entity TypedDicts; `DocEntry` correctly carries only `id` + `created_at` (no `updated_at`/`version`) per its append-only nature
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (~60 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 39 error IDs + HTTP status map, registered with the framework via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions plus `assert_security_conservation` (lodged == held+released+applied) and `assert_property_mass_conservation`
- `factories.py`, `constants.py` (PROVISIONAL_PCT 0.12, SECURITY_MULTIPLIER 1.25, tier caps, RISK_ADD/ENV_ADD, STANDBY/DEMURRAGE factors, SCOPIC uplift, pollutant multipliers, 6h weather buffer, PERMIT_MAP, default clock)
- `test_users.py` — 7 roles (all opaque identity) with shared constants + `make_*_headers` builders for SoD scenarios
- `fixtures.py` — composite chains: `setup_assessed_casualty` → `setup_planned_casualty` → `setup_signed_contract` → `setup_active_contract` → `setup_running_phase` → `setup_completed_operation` → `setup_computed_award`, plus `setup_verified_lot`/`setup_liened_lot`/doc-pack helpers. OCC threading (`expected_casualty_version`) re-reads the casualty version at submission time

**`/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/test_suite/`** (Stage 2) — `conftest.py` + 13 numbered test files, **100 tests**

## Audit results (all green)
- **Coverage:** 19/19 difficulty instances with ≥2 tests each (38 tests); 62/62 non-stub corner instances with ≥1 test; both `excluded_because` stubs (`cascading_side_effects_layer_coverage`, `dual_variant_calculation_layer_coverage`) correctly not translated
- **C4 tags:** 100/100 docstrings end with exactly one `Design:` line; every tag resolves to a real instance in the source YAML
- **C1 verbatim:** every docstring contains at least one ≥8-word fragment surviving literal grep of PRD.md
- **Error IDs:** all 39 asserted IDs appear in PRD prose (§2–§4), not just the §5 table
- **No** `skip`/`skipif`/`xfail`, no scaffold references, pytest collects all 100 tests

## PRD-adjudication decisions (three deliberate relaxations)
Three corner instances assert a specific error where PRD text supports two readings, so `validate_error_is_one_of` was used per the sanctioned error-precedence pattern (each docstring cites both PRD readings):
- `redeliver_while_liened_rejected` — §3.8 names `ERR_LIEN_ACTIVE` for the attempt while §2.7's pipeline puts the from-state `ERR_INVALID_STATE_TRANSITION` first
- `casualty_close_blocked_rejected` — §3.9 names `ERR_CASUALTY_NOT_CLOSABLE` for unsettled contracts; §2.7 permits the from-state rejection when the casualty isn't `OPERATIONS_COMPLETE`
- `no_cure_termination_cascade` (award-after-termination sub-assertion only) — §3.9 names `ERR_CONTRACT_NOT_ACTIVE` for award creation, while §2.7 permits `ERR_ALREADY_TERMINAL`/`ERR_INVALID_STATE_TRANSITION` on the terminal contract

No instances were skipped: every non-stub instance in both indices had verbatim PRD coverage with uniquely-derivable outcomes (modulo the three noted ambiguities).

## Step 6: Generate Implementation — 2026-08-11T23:57:40.477Z

Both smoke suites pass on fresh boots. The implementation is complete.

## What was built

All files under `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/workspace/implementation/`:

- **`app.py`** (~1,500 lines) — single-file Flask implementation covering all 60+ endpoints from the scaffold: logical clock with permit/weather-window expiry sweep, casualties, assessments (with supersede + OCC on `expected_casualty_version`), plans (revision loop), contracts (offer/counter negotiation cycle with OCC on `expected_contract_version`, sign with provisional-award/security computation, activate with safety-before-fiscal gates, MUTUAL/NO_CURE termination with the full cascade, settle), securities (conserved bucket accounting), permits (cyclic grant/suspend/reinstate + revoke + sweep), equipment assets/charters (half-open overlap, standby accrual, pinned rounding-order cost at off-hire, overrun flag), weather windows, operation phases (env/weather/permit/charter gates at activation, hold/resume loops, cascade B bubble-up), pollution events (posture derivation, cascade A, escalate/contain/verify-clean, provisional-tariff vs final-actual special compensation with SCOPIC netting), recovered property (parallel custody/documentation dimensions, liens, mass-conserved disposition with terminal-method semantics), storage sites (aggregate capacity), salvage awards (tiered final calculation in exact rational arithmetic, arbitration/appeal loop, mark-paid with lien-lift cascade), and doc packs/entries (live completeness evaluation, exact-100 submit gate, review rework loop).
- **`requirements.txt`** — `flask>=2.2`.
- **`start.sh`** — executable, guarded dependency install (no-op when flask importable), `exec python3 app.py` in the foreground, binds `0.0.0.0:$PORT` (default 10000).

## Key design decisions (all traceable to PRD/scaffold)

- Envelope: `meta`/`response_type`/`data`, pagination fields (`limit`/`offset`/`total_count`/`has_more`) in `meta`, default limit 10 clamped to [1,100], lists sorted by `created_at` asc with insertion-order tiebreak.
- Logical clock defaults to 2026-05-01T00:00:00Z, drives all recorded timestamps; sweep expires only when `now > valid_to`/`window_end` (strict).
- Validation pipeline priority order implemented literally: schema → auth headers → role → existence → SoD → state (terminal precedence) → safety → temporal → referential → constraint → fiscal → OCC. Notable precedence points: `ERR_ENV_CLEARANCE_REQUIRED` before `ERR_SECURITY_INSUFFICIENT` at activate; `ERR_DOCS_NOT_ACCEPTED` (p8) before security-closed (p10) at settle; window-open check (p7) before contract-state check (p8) at on-hire; overlap (p7) before contract/asset-class (p8) at booking.
- Money math in `Fraction` with round-half-up; charter cost rounds each rate line to integer cents before multiplying by days; award base in exact rationals with a single rounding after enhancement and the cap applied after rounding.
- Doc entry refs: id existing nowhere → 404 `ERR_NOT_FOUND`; existing but wrong type/casualty/qualifying state → 422 `ERR_DOC_ENTRY_INVALID`.
- Contract-state-gated sub-resource creation (securities, phases, award, doc-packs) returns `ERR_CONTRACT_NOT_ACTIVE` for any non-qualifying state including terminal, per PRD prose ("any other contract state is rejected with ERR_CONTRACT_NOT_ACTIVE").
- No seeding at startup — the store starts completely empty on every boot.

## Verification

Two self-written end-to-end smoke suites (`/tmp/salvage_smoke.py`, `/tmp/salvage_smoke2.py`) exercising the full lifecycle plus edge cases (OCC 412s, SoD, supersede, negotiation cycle, exact provisional/security/final award numbers, charter day-bucket math including demurrage strict-greater trigger and standby accrual across weather/env holds, cascade A/B, no-cure termination cascade, lien sale, SCOPIC netting to zero, permit/window sweep boundaries, weather-limit inclusive boundary, doc-pack completeness at exactly 100) — **0 failures on fresh server boots**, and `bash start.sh` verified to boot cleanly and serve an empty store.

Orchestrator pre-sweep check: implementation registers exactly the 86 (method, path) route pairs declared in SCAFFOLD.yaml — 0 missing, 0 extra.

## Step 7: Run Tests and Iterate — 2026-08-12T00:07:34.110Z

## Summary

**Iterations run: 2** (iteration 1: 91/100 in all 8 rounds, same 9 failures in every round; iteration 2: 100/100 in all 8 rounds — zero union failures).

**Tests deleted: none.** Every failing test traced to a verbatim PRD rule with uniquely derivable outcome; no PRD-silence or collapse-pattern cases arose.

**Fixes applied to `test_suite/` (1):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/test_suite/test_09_pollution.py` — `TestExposureTariffVsActual.test_final_exposure_uses_actual_cost_times_pollutant_multiplier`: the test invoked `on_hire_charter`/`off_hire_charter` with `environmental_officer_headers`, but PRD §4 restricts both endpoints to `SalvageMaster` (implementation correctly returned `ERR_FORBIDDEN_ROLE`). Switched those two calls to `salvage_master_headers` (contain/verify-clean correctly remain `EnvironmentalOfficer`).

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `implementation/` (2, both in `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/workspace/implementation/app.py`):**
1. `mint()` (line 248) and doc-entry creation (line ~2428): changed `uuid.uuid4().hex` to `str(uuid.uuid4())` — PRD §2.5 requires "a server-minted UUID"; the undashed hex form failed the canonical UUID shape asserted by `assert_*` entity checks (root cause of 6 failures: casualty creation, list pagination, assessment supersede, charter day buckets, lien sale, final award, doc entry shape).
2. `activate_phase()` permit gate: when no `GRANTED` permit of a required agency exists but one of that agency is `EXPIRED`, raise `ERR_PERMIT_NOT_VALID` instead of `ERR_PERMIT_MISSING` — PRD §3.5 states verbatim: "A permit swept to `EXPIRED` by the clock fails this validity check like any other out-of-window permit." SUSPENDED/absent permits still yield `ERR_PERMIT_MISSING` per "its absence is `ERR_PERMIT_MISSING`", keeping `test_permit_suspend_reinstate_cycle_gates_activation` green.

No endpoint, field, or capability was added beyond PRD; storage remains purely in-memory; no assertion was weakened (the one pre-existing `validate_error_is_one_of` usages were left untouched as they already reflect the documented PRD ambiguity pattern).

Orchestrator disk verification: all 8 `results.*.json` files present; each shows passed=100, failed=0, total=100.

## Step 8: Finalize PRD — 2026-08-12T00:10:21.466Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/workspace/PRD_FINALIZED.md` written.

## Summary

**Line counts:** PRD.md 349 lines, PRD_FINALIZED.md 349 lines — 0% line-count delta (one in-place sentence revision, no lines added or removed).

**Changes (1 edit):**
- §2.5 — revise — "The `id` is a server-minted UUID with no type prefix." extended with ", rendered in the canonical 36-character hyphenated form of five hexadecimal groups separated by hyphens (8-4-4-4-12 digits, as produced for example by Python's `str(uuid.uuid4())`)." — `implementation/app.py:248` (`mint()`, sole constructor for all primary resources) and `implementation/app.py:2434` (DocEntry inline mint). Step 7 changed both sites from `uuid.uuid4().hex` (undashed) to `str(uuid.uuid4())`; the PRD's "server-minted UUID" did not pin the textual rendering, so the choice was PRD-silent.

**Diff items requiring no edit:**
- Permit gate (§3.5, impl `app.py:1625-1640`): the Step 7 fix changed the *implementation* to match PRD text that already pins behavior verbatim — "A permit swept to `EXPIRED` by the clock fails this validity check like any other out-of-window permit" (EXPIRED→`ERR_PERMIT_NOT_VALID`) and "its absence is `ERR_PERMIT_MISSING`" covers every other non-GRANTED case (SUSPENDED/REQUESTED/REVOKED/never-filed→MISSING). PRD already determines current impl behavior; prose kept verbatim per method.
- `test_09_pollution.py` role fix: pure test-fixture bug; PRD §4 already restricts `on-hire`/`off-hire` to `SalvageMaster`. No PRD impact.

**Per-edit pre-edit search log (edit 1, the only edit):**
- (a) Subject: textual rendering of the server-minted resource `id`.
- (b) Impl paths enumerated: grepped `uuid` across `app.py` — exactly two mint sites: `mint()` at app.py:245-253 (all primary resources; verified representative creation callsites at lines 696, 780, 859, 965, 1191, 1270, 1345 all route through it) and DocEntry creation at app.py:2432-2436; both produce `str(uuid.uuid4())`. Checked for collisions: the envelope's `api_request_id` (`req_`-prefixed) is a different field governed by §2.2 — the new wording scopes strictly to the resource `id`, so no conflict. Incoming IDs are opaque string dict lookups via `get_or_404` (app.py:261-264), never parsed or reformatted, so no other path constrains the format.
- (c) Wording adjustment: none needed beyond scoping — the canonical hyphenated description is satisfied identically by both mint sites; no enumerated path exhibits a different or narrower format.

## Step 9: Complete PRD — 2026-08-12T00:16:31.193Z

PRD_COMPLETED.md produced at `/home/ubuntu/github/CodingPRD/tasks/task_1211_marine_salvage_wreck_removal/workspace/PRD_COMPLETED.md`.

**Source:** `PRD_FINALIZED.md` (349 lines / 65,989 chars) → `PRD_COMPLETED.md` (349 lines / 68,246 chars), char-delta +2,238. Line count unchanged: every change was an inline insert/revision within existing paragraphs; no new sections, paragraphs, or invented behavior.

**Counts:** 16 ambiguity-pins, 2 mismatch-revisions (18 edited passages total; two passages each combined one ambiguity-pin with one mismatch-revision).

Changes:

- §2.3 — insert — ambiguity — non-integer limit/offset fall back to defaults (10/0), out-of-range values clamped to [1,100] and ≥0 rather than rejected; list sort ties broken by internal creation sequence — app.py:268-281
- §2.4 — revise — ambiguity — logical clock also governs `created_at`/`updated_at`; envelope `api_request_timestamp` alone reads wall-clock — app.py:145-146, 249-258
- §2.4 — insert — ambiguity — `expired_permit_ids`/`expired_window_ids` listed in creation order — app.py:654-664
- §2.5 — revise — ambiguity — `version` starts at 1 (was "its initial value") — app.py:251
- §2.8 — insert — ambiguity — a charter body's `pollution_event_id` added to the existence-checked reference list (`ERR_NOT_FOUND`) — app.py:1395-1396
- §3.1 — insert — ambiguity — `casualty_seq` starts at 1, increments by 1 per casualty — app.py:762-763
- §3.3 — insert — ambiguity — contract creation performs only existence checks: `plan_id` need not reference a plan of the same casualty or in any status, and no casualty lifecycle precondition applies — app.py:946-947
- §3.3 — revise — ambiguity — `NO_CURE` from `DRAFT`/`OFFERED`/`COUNTERED`/`SIGNED` is `ERR_INVALID_STATE_TRANSITION` regardless of form; `ERR_NO_CURE_REQUIRES_NCNP` arises only from `ACTIVE` — app.py:1108-1119
- §3.6 — insert — ambiguity — `OFF_HIRE` and `CANCELLED` pinned as the charter terminal states (`ERR_ALREADY_TERMINAL` on further action) — app.py:1466-1467, 1490-1491
- §3.6 — revise — ambiguity — off-hire writes the recomputed `cost_to_date_cents` (and re-evaluated `overrun_flag`) onto every contract of the casualty, not just one — app.py:594-615
- §3.6 — insert — ambiguity — a non-`OPEN` weather window at phase activation yields `ERR_WEATHER_WINDOW_INFEASIBLE` — app.py:1614-1615
- §3.7 — insert — ambiguity — netting's "the contract" pinned as the casualty's latest-created contract for which an award exists — app.py:512-518
- §3.8 — insert — ambiguity — `verified_value_cents` is a non-negative integer; `lien_amount_cents` a positive integer; dispose `tonnes` positive — app.py:1931, 1965, 1987
- §3.8 — insert — ambiguity — disposition defined only from `SECURED_ASHORE`/`LIENED` (terminal custody → `ERR_ALREADY_TERMINAL`; `SALVED` → `ERR_INVALID_STATE_TRANSITION`); scrapping a liened lot and all dispose documentation shortfalls → `ERR_INVALID_STATE_TRANSITION`, with `ERR_LIEN_ACTIVE` reserved for the lien/award gates — app.py:1994-2044
- §3.8 — revise — mismatch — partial disposition leaves custody unchanged (a partial lien sale leaves the lot `LIENED` with `lien_amount_cents` intact); PRD previously said partial disposition leaves custody in `SECURED_ASHORE` — app.py:2049-2064
- §3.9 — insert — ambiguity — `agreed_amount_cents` and `awarded_amount_cents` are non-negative integers — app.py:2183, 2221
- §3.9 — revise — mismatch — a doc-entry `ref_id` naming no existing record is `ERR_NOT_FOUND` (per §2.8); `ERR_DOC_ENTRY_INVALID` covers existing-but-wrong-type/wrong-casualty/unqualified-state records (PRD previously lumped missing references under `ERR_DOC_ENTRY_INVALID`, conflicting with §2.8) — app.py:2413-2421
- §3.9 — insert — ambiguity — entries appendable only while the pack is `COMPILING` (`SUBMITTED` → `ERR_INVALID_STATE_TRANSITION`, `ACCEPTED` → `ERR_ALREADY_TERMINAL`); `completeness_pct` is an integer when integral, else rounded to two decimals; counters evaluated at pack creation, on every append, and at submission — app.py:2322, 2355, 2422-2426

Everything else in the implementation (endpoint table, role set, error catalogue, validation pipeline order, cascades A/B/termination, all calculation formulas and rounding orders, conservation invariants, state machines) was already uniquely pinned by PRD_FINALIZED.md and required no change.
