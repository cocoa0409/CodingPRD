# Worklog — task_1136_dredging_project_operations

## Step 1: Create task directory — 2026-08-10T22:47:00.000Z

Task directory pre-assigned by caller: `tasks/task_1136_dredging_project_operations` with `workspace/` subdirectory already present. Step 1 auto-index scan skipped per instructions; recorded as done.

## Step 2: Generate Scaffold — 2026-08-10T23:27:00.000Z

All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/` and the lint verdict is clean.

## Summary

**Complexity profile** (deliberately exceeds the §0.4 Expert band per the "harder than expert" directive):
- Archetypes: `ledger_reconciliation` (primary — in-place survey vs scow measurement produce divergent payable quantities for identical material, with a 15% reconciliation tolerance that auto-forks FINAL certificates into AUDIT_HOLD) + `posture_driven_gating` (secondary — Project.compliance_posture CLEAR/RESTRICTED/SUSPENDED derived from permit window, turbidity readings, species sightings gates all dredge-event operations)
- Layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency
- Topology flat (all FK references, no URL nesting); shape cyclic; role model segregation_of_duties (5 opaque roles: OwnerEngineer, ContractorOps, SurveyParty, EnvironmentalMonitor, SiteOperator — SoD enforced by comparing X-User-ID against recorded `*_by_user_id` fields on surveys/tickets/claims/certificates); consistency immediate

**Counts**: 13 entities / 64 endpoints / 31 error codes / 9 calculations / 12 validations / 5 roles; §1.8: 19 instances across all 9 rules (combinatorial_formula has 3 — one per mode a/b/c); §1.9: 46 instances (44 active + 2 excluded_because stubs) across 8 guide sections.

**State machines (12)**: Project (PLANNED→ACTIVE→CLOSED_OUT, compound child-gated), Permit (ISSUED→EXPIRED clock-auto), Reach (cyclic deficiency loop POST_SURVEY_SUBMITTED→DREDGING), DredgePlant (REGISTERED↔OUT_OF_SERVICE→RETIRED), DredgePlan (cyclic CHANGES_REQUESTED↔SUBMITTED + create-with-supersede APPROVED→SUPERSEDED), Survey (SUBMITTED→ACCEPTED/REJECTED, ACCEPTED→SUPERSEDED self-referential), DredgeEvent (cyclic ACTIVE↔SHUTDOWN with SPECIES/TURBIDITY/EQUIPMENT/WINDOW reasons), PlacementTicket (REPORTED→CONFIRMED/REJECTED, CONFIRMED→VOIDED compensating), DisposalSite (OPEN↔FULL cyclic on exact capacity, →CLOSED), StandbyClaim (SUBMITTED→APPROVED/DENIED, SETTLED↔APPROVED compensation), SpeciesSighting (ACTIVE→CLEARED with cooldown), PaymentCertificate (branching fork DRAFT→SUBMITTED vs DRAFT→AUDIT_HOLD, dispute loop DISPUTED→DRAFT, CERTIFIED→PAID/VOIDED).

**Key design decisions worth recording**:
- Dual measurement legs pinned: per-ticket `round_half_up(witnessed/bulking_factor, 2)` THEN sum (sum-then-divide declared a spec violation); FINAL quantity follows `measurement_basis`, INTERIM always scow-derived
- Settlement circularity broken by `allowed_days_frozen` snapshot at activation (later plan supersedes provably cannot re-freeze — asserted with literal LD arithmetic)
- Two temporal-overlap geometries: permit windows CLOSED (touching endpoints conflict) vs plant assignments HALF-OPEN (touching allowed)
- OCC on Project.version (plan approve) and Reach.version (survey accept) — both true CREATE-with-supersede races per §1.2.1's filter
- Logical clock endpoint with mandatory default `2026-05-01T00:00:00Z`; window exit auto-shuts ACTIVE events with reason WINDOW
- Fixes applied during the build: added `material_class` to DredgePlan (referenced by production_estimate), WINDOW shutdown reason (clock cascade), `supersedes_survey_id?` filter on GET /surveys (FK reverse-reachability), repaired the turbidity boundary instance (window advance isolates the 49 vs 50 readings from averaging), and re-chained the unapproved-claim corner (claims need real accumulated shutdown hours to exist)

**Lint verdict (verbatim)**:
```
Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     13
  §1.8 instances scanned:     19
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  926

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-08-10T23:28:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1136_dredging_project_operations/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-10T23:40:00.000Z

All audits pass. The PRD is complete and verified. Final summary:

## PRD Generation Complete — task_1136_dredging_project_operations

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/workspace/PRD.md` — **364 lines**, ends at §5 with no audit footer.

### Section map → scaffold coverage

| PRD section | Scaffold sections covered |
|---|---|
| §1 Introduction (3 paragraphs: dual-measurement tension, compliance regime, logical clock) | `scenario`, `complexity_profile` |
| §2.1 Roles & auth (5 roles, all individually named, all `identity: opaque` translated; recorded-anchor fields enumerated) | §1.7 `roles`, auth errors |
| §2.2 Response envelope — **byte-verbatim** from `section-2.2-response-structure.md` (verified programmatically) | §1.0 `response_envelope` |
| §2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, 4 meta fields) | §1.0 pagination |
| §2.4 Logical Clock (default 2026-05-01T00:00:00Z, never wall-clock, monotonic, `to_iso8601`/`current_utc`, 3 clock-set cascades incl. `WINDOW` shutdowns) | clock endpoint + side_effects, `DEFAULT_LOGICAL_NOW` |
| §2.5 Common Resource Properties (UUID/no prefix, ISO-8601 3-fraction digits, version semantics; TurbidityReading's `common_fields: false` exception stated explicitly) | §1.1 common_fields |
| §2.6 Compliance Posture Derivation (full algorithm: closed governing window → sighting → ceiling (equality suspends) → trailing half-open average (equality restricts, full precision) → `CLEAR`; empty window never restricts; all recompute triggers) | §1.3 `compliance_posture` |
| §2.7 OCC (both `concurrency_rules`: endpoint + `expected_*_version` + exact error id + 412 + supersede rationale; no race framing; "no other endpoint takes a version field") | §1.2.1 |
| §2.8 Segregation of Duties (all 7 applies_to endpoints enumerated against their anchor fields) | §1.7 role_model, §1.4 priority 8 |
| §2.9 Evaluation Order (all 12 validation priorities in fixed class order with ids+statuses; two worked orderings) | §1.4 `validations` |
| §2.10 Reference Integrity (flat topology, left-to-right path→body FK order, ticket→event→reach→project same-project chain, reverse reachability) | §1.4 priority 3, entity_topology |
| §2.11 Measurement & Rounding (2dp half-up, integer cents, both pinned rounding orders, "sum-then-divide is a violation", full-precision average exception) | §1.3 precision fields |
| §3.1–3.9 (setup/activation → permits → plant/plan/estimate → surveys/reach loop → events/shutdown/resume → monitoring → placement/capacity → standby → certificates/reconciliation/close-out) | All 46 transitions, 9 calculations, all endpoint side_effects, all constants (weather 20%, material factors, 30/50-ft depth bands, 80% tier split, 90/75% rates, 4-hr deductible, 0.5 species multiplier, 15% tolerance) |

§4: 64-row endpoint table, 4 columns only. §5: 31-row error catalogue, 2 columns only.

### Hard-contract audit results (all PASS)

- **Contract 1 Field coverage**: 86/86 entity fields, 4/4 endpoint-only names (`to_iso8601`, `current_utc`, both OCC fields), 4/4 common fields, 11/11 query-param names — 0 missing. (First audit pass was a false alarm: my regex desynced on the §2.2 fenced JSON blocks; stripping fences before extraction fixed the tooling, not the PRD.)
- **Contract 2 Rule coverage**: 12/12 validation priority classes with explicit ordering prose; 2/2 OCC rules fully named; 46/46 transitions (from/to + preconditions + error ids + side effects); 9/9 calculations reconstructible from prose (boundary inclusivity, rounding order, pinned evaluation order all preserved); 31/31 error ids trigger-matched in §2/§3 prose (verified: none appear only in §5); all endpoint side_effects and applies_to scopes expressed; sibling branches symmetric (retire/close/complete pairs, submit fork, PRE/POST accept, INTERIM/FINAL, NOMINAL/RISK_ADJUSTED).
- **Contract 3 §3 path purity**: 497 backticked tokens scanned, 0 path tokens, 0 bare-method tokens, 0 method+path combos.

Additional scans: 37/37 state values present, 30/30 enum values present, zero fuzzy words (`approximately`/`roughly`/etc.), zero operator syntax (`==`, `>=`, `+=`…) in prose outside backticks, §2.2 byte-identical to the canonical source.

### Wording decisions worth recording

1. **HTTP-status conflict resolved**: scaffold §1.4 priority-10 row labels the whole capacity class "422" but the §1.6 catalog pins `ERR_DISPOSAL_CAPACITY_EXCEEDED` at 409. The catalog (per-skill authority for per-error status) won — 409 in §2.9, §3.7, and §5.
2. **`(1 − WEATHER_ALLOWANCE_PCT)` rendered as "multiplied by four-fifths"** alongside "twenty-percent weather allowance" — keeps the 0.20 factor exactly reconstructible without operator syntax.
3. **Clamp semantics** of the waterfall rendered as "the smaller of the not-yet-allocated quantity and the room remaining… never less than zero", per tier, with cursor/cap operands named — passes the step-for-step reconstruction test.
4. **"Plant availability" at event creation** (endpoint description) was deliberately *not* turned into a free-standing plant-status check, since no error id exists for it; it is expressed through the scaffolded `ERR_PLAN_NOT_APPROVED` project+plant window-coverage gate.
5. **Audit-trail constraint honored**: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no other `task_*` directory was read.

## Step 5: Generate Unit Tests — 2026-08-11T00:05:00.000Z

Generation complete. All artifacts live under `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/`.

## Test counts

- **Queue A (Difficulty): 38 tests** — all 19 instances × exactly 2 tests each, tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner): 46 tests** — all 46 non-stub instances × 1 test each, tagged `Design: Corner/<section>/<instance.name>`.
- **Total: 84 tests** across 10 numbered files; 84 tags, exactly one per test, always the docstring's last line.

## Instances skipped

- **None for PRD-silence** — all 65 non-stub instances passed the two-condition filter.
- **3 corner stubs not translated** (per spec): `survey_accept_from_rejected_returns_invalid_state`, `ticket_confirm_capacity_debit_side_effect`, `ticket_create_on_full_site_rejected`. All three `difficulty_instance` cross-references verified to resolve; the owning queue-A instances each carry 2 tests.

## Adjudications worth recording (PRD-first corrections, not skips)

1. `Difficulty/dual_variant_calc/final_certificate_in_place_vs_scow_divergence`: the design's own chain (one 1609-cy ticket at bulking 1.60 → scow 1005.63 vs survey 2000.00) yields reconciliation delta 49.7% > 15%, which per PRD §3.9 forks to AUDIT_HOLD — contradicting the design's asserted `SUBMITTED` (its "0.563 pct" note assumed two tickets). The test asserts the PRD-uniquely-derivable outcome (quantity 2000.00, divergent scow total 1005.63, status AUDIT_HOLD).
2. `Corner/entities/project_creation_applies_defaults`: dropped the `version == 1` literal — PRD §2.5 defines version semantics but never pins an initial value (not uniquely derivable). All other assertions kept.
3. `Corner/complexity_layers/occ_stale_project_version_on_plan_approve`: the design's setup is unreachable as written (activate requires an APPROVED plan, so it would 409 and never bump the version). Repaired with a two-plan setup that preserves the instance's distinguishing aspect verbatim (stale pre-activation version → ERR_STALE_PROJECT_VERSION 412; fresh version → APPROVED, planA SUPERSEDED per PRD §3.3).

## Helper inventory

`test_helpers/`: `types.py` (13 TypedDicts, 19 enums; TurbidityReading correctly omits updated_at/version), `api_client.py` (64 endpoint methods, one per §4 row), `api_errors.py` (31 error ids + HTTP map registered with the framework), `assertions.py` (13 entity assertions + capacity/ledger/snapshot invariant checkers), `factories.py` (13 input-only payload factories), `constants.py` (weather allowance, material factors, deductible, tolerance, tier rates), `test_users.py` (5 shared role headers on canonical opaque ids eng-1/ops-1/surv-1/mon-1/site-1 + 5 per-id builders for cross-id SoD tests), `fixtures.py` (~30 atomic one-call helpers + 10 composite fixtures: active project, dredging reach, pre-surveyed reach, completed event(s), confirmed ticket, species/equipment shutdown cycles, approved claim, accepted reach), `__init__.py` barrel.

`test_suite/`: `conftest.py` (session api + 5 role-header fixtures) + `test_01`…`test_10` organized by concern (contract setup/clock, plans/estimates, surveys/reach loop, events/posture, shutdown cascades, placement/capacity, standby, payment measurement, certificate lifecycle, RBAC/auth).

## Stage-gate results (all automated, all green)

- pytest collection: **84/84 clean**, no import errors.
- Coverage: every queue-A instance ≥2 tags; every non-stub queue-B instance ≥1; no phantom tags; no dual/untagged tests.
- C1 verbatim: 127 rule-bearing quoted fragments (≥8 words) all survive literal grep of PRD.md (six initial failures from `**bold**` prefixes/elisions were fixed).
- Error-id audit: every asserted `ApiErrorId` is named in PRD prose (§2/§3) and cited in the test's docstring.
- No `skip`/`skipif`/`xfail` anywhere; no "scaffold"/table references in generated code; pyflakes reports no real defects.

## Fixture-design decisions

- All roles are opaque, so shared header constants are canonical; SoD is exercised by threading a recorded id onto a different role's headers via `make_*_headers` (e.g. SiteOperator carrying `ops-1`).
- `approve_plan`/`accept_survey` re-GET the parent's current version internally, making fixtures immune to OCC version bumps from intermediate mutations (activation, prior accepts).
- Monotonic-clock discipline: every fixture only advances the logical clock; shutdown cycles settle exact hours (10.0/8.0/4.0) so standby-accumulation assertions are literal.
- Quantities compared with `pytest.approx(..., abs=1e-4)` — tight enough that the pinned per-ticket-rounding pair (2011.26 vs the forbidden 2011.25) discriminates; all money asserted as exact integer cents.

## Step 6: Generate Implementation — 2026-08-11T00:05:30.000Z

Implementation complete and verified. Final summary:

## File inventory — `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher: guarded `pip install` (no-op once flask importable), `exec python3 app.py` |
| `requirements.txt` | 1 | flask>=3.0,<4.0 |
| `app.py` | 65 | App factory, blueprint registration, ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 38 | In-memory store (13 dicts) + logical clock default `2026-05-01T00:00:00Z`; no disk persistence, no seeding |
| `errors.py` | 44 | ApiError + all 31 error-ID constants from the scaffold catalogue |
| `util.py` | 182 | ISO-8601 parse/format (3 fractional digits), Decimal round-half-up helpers, shape validators, pagination |
| `response.py` | 37 | Envelope: `meta`/`response_type`/`data`; list meta adds `limit/offset/total_count/has_more` |
| `middleware.py` | 44 | `X-User-ID`/`X-User-Role` auth (401) + per-endpoint role check (403); five exact role names |
| `services.py` | 539 | Posture derivation, clock cascade, production estimate, removed-quantity identity, scow/survey totals, tiered waterfall, settlement totals, serializers |
| `routes/common.py` | 19 | List helper: filters, `created_at`-asc + insertion-seq tie-break, pagination |
| `routes/clock.py` 23 · `projects.py` 153 · `permits.py` 93 · `reaches.py` 111 · `plants.py` 107 · `plans.py` 205 · `surveys.py` 196 · `events.py` 159 · `monitoring.py` 161 · `disposal.py` 253 · `claims.py` 179 · `certs.py` 291 | | One module per resource group |

Total ~2910 lines.

## Route-pair diff result
Parsed SCAFFOLD.yaml §1.5 (64 endpoint entries) and compared normalized `(method, path)` pairs against Flask's `url_map` (Flask's built-in `/static` route was disabled via `static_folder=None` to eliminate the only extra): **64 declared == 64 registered, missing: NONE, extra: NONE — exact match.**

## Smoke test (fresh-boot, curl-level via urllib)
- Booted via `PORT=<n> bash start.sh` from a fresh process twice; confirmed empty store on both boots (no carry-over, no seeding) and backwards-clock rejection proving the 2026-05-01T00:00:00Z default.
- 87-check end-to-end flow passed 86/87 — the one "FAIL" is a mislabeled assertion in my own smoke script: the FINAL certificate with reconciliation delta 51.46% > 15% correctly forked to AUDIT_HOLD (confirmed by the subsequent passing checks). Verified: 401/403 auth ordering; permit closed-interval overlap (touching endpoints conflict); production estimate (1700/1360 cy/day, 8 risk days); plan-approve OCC 412 then 200 with `Project.version` bump; activation freeze `allowed_days_frozen=8`; survey OCC-precedes-SoD (412 masks 403); reach acceptance loop; species sighting → SUSPENDED → SHUTDOWN(SPECIES) → cooldown clear at exact equality → resume with 96h accrual; ceiling turbidity → SHUTDOWN(TURBIDITY); complete-from-shutdown accrual (144h); ticket confirm SoD + per-ticket in-situ rounding (6500/1.30=5000); claim deductible/multiplier (140h × 40000 × 0.5 = 2,800,000) and 422 over-claim; INTERIM cert math (qty 5000, amount 7,500,000, total 10,300,000), certify ledger movement + claim SETTLED + cursor 5000, pay, void-of-PAID 409; FINAL with LD 3,200,000 (40 actual vs 8 frozen), AUDIT_HOLD fork, override-note 400-before-SoD, override certify, pay, close-out; pagination meta.

## Design decisions worth recording
- **Clock**: single logical now in `db.store`; all business timestamps (`created_at`, `updated_at`, `ended_utc`, `cleared_at`, `last_shutdown_at`) come from it; only the envelope `meta.api_request_timestamp` uses wall clock. Clock-set cascade: expire ISSUED permits past `window_end_utc` → recompute every project's posture → shut down ACTIVE events with cause-mapped reason (no-governing-permit→WINDOW, active-sighting→SPECIES, ceiling-reading→TURBIDITY).
- **Posture wiring**: stored on Project, recomputed at every scaffold-listed trigger (permit create, clock set, reading create, sighting create/clear); `touch()` (updated_at+version) only when the derived value actually changes. Trailing turbidity window is half-open `(now-hours, now]`, average compared at full Decimal precision, equality suspends/restricts as specified.
- **Rounding**: `Decimal` everywhere; ROUND_HALF_UP; pinned orders honored — per-ticket `in_situ` rounded to 2dp at confirm before summation; per-tier line amounts rounded to whole cents before summing; risk rate = r2(nominal × 0.8) where nominal is already r2-rounded; durations integer ceiling; plan window feasibility uses floor(span/24h).
- **Validation pipeline**: per-endpoint checks follow PRD §2.9 class order — auth → role → existence (path left-to-right, then body FKs; cross-project references → 404; unresolvable array elements → 400) → OCC 412 → shape 400 → state gates → posture gates → SoD → temporal → capacity/aggregate → referenced-entity state → fiscal. On plan approve this means overlap (409) and feasibility (422) fire *before* plant-availability/permit checks, per the PRD illustration (PRD overrides scaffold `state_machines.preconditions` order).
- **OCC**: `expected_project_version` / `expected_reach_version` required on the two OCC endpoints — provided-and-mismatched → 412; missing/malformed → 400. Cascades bump the concurrency field on every touched resource.
- **Misc**: events/tickets carry internal `_project_id` (denormalized at creation from the reach/event chain) for posture/standby/close-out aggregates; internal `_`-keys never serialized. Certificate DRAFT/revised state represents the cleared snapshot as nulls; per-reach line quantities stored internally at submit to drive cursor increments on certify and decrements on void. TurbidityReading carries no `updated_at`/`version` per the PRD 2.5 exception.

## Step 7: Run tests and iterate — 2026-08-11T00:40:00.000Z

All 8 rounds clean with the final artifact. The gate is satisfied.

## Summary

**Iterations run:** 5 sweeps (1 baseline + 1 post-fix + 1 under foreign cross-pipeline load + 1 instrumented + 1 final confirmation) plus 1 single-round diagnostic.

**Tests deleted:** none — every failing assertion traced to a verbatim PRD rule; no test-helper changes were needed.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/workspace/implementation/routes/*.py` (11 files, 13 entity-creation sites in projects, permits, reaches, plants, plans, surveys, events, monitoring ×2, disposal ×2, claims, certs): `"id": uuid.uuid4().hex` → `"id": str(uuid.uuid4())`. PRD line 82 states verbatim: *"Every resource carries an `id`, a server-minted UUID with no type prefix."* `.hex` emits 32 hex chars without dashes — not a canonical RFC-4122 UUID string — which tripped `is_valid_uuid` in 6 tests (TestCreationDefaults ×3, TestPayableComputation ×2, TestProductionEstimateVariants ×1), deterministically in all 8 baseline rounds. The `api_request_id` field was correctly left as `"req_" + hex[:24]` per PRD lines 30/42 (only a `req_` prefix is required there).

2. `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/workspace/implementation/start.sh`: dependency probe changed from `python3 -c "import flask"` to `importlib.util.find_spec('flask')` — eliminates a throwaway full flask import on every server boot (~450ms → ~266ms boot). This widens the margin against the runner's 15s restart-poll window during the 8-round sweep (672 boots per sweep on a shared 8-core host). The install-when-missing contract is preserved.

**Infra flakiness diagnosis (no artifact change warranted):** sweeps 2–3 showed intermittent `could not be restarted` setup errors and mid-test `Connection reset by peer` errors, correlated in time with another pipeline's concurrent 8-round sweep on this shared host (observed via the shared port registry). A single-round diagnostic run passed 84/84 in 49s; an instrumented sweep with server stderr captured showed zero crash tracebacks. Two consecutive final 8-round sweeps passed 84/84 × 8, confirming the flakes were contention-driven, not code defects.

**Final state:** 8/8 rounds × 84/84 tests passing, two consecutive clean sweeps with the final code.

## Step 8: Finalize PRD — 2026-08-11T00:45:00.000Z

PRD_FINALIZED.md is written and verified byte-identical to PRD.md. Both step_7_diff items resolved to no-edit.

## Summary

**PRD.md vs PRD_FINALIZED.md:** 363 lines vs 363 lines — 0% delta, byte-identical (verified with `cmp`). Zero edits; this is the legitimate byte-copy outcome.

**Changes:** none.

**Why neither diff item warranted an edit:**

- **Item 1 (UUID format, 13 entity-creation sites)** — impl-side fix toward a rule PRD already pins verbatim. PRD line 82 ("Every resource carries an `id`, a server-minted UUID with no type prefix") uniquely determines the canonical RFC-4122 hyphenated string: "UUID" is a term of art whose standard textual form is the 8-4-4-4-12 dashed representation; `uuid.uuid4().hex`'s 32-char undashed output is the hex *of* a UUID, not a UUID string, and fails canonical validation. Step 7 moved the implementation *toward* the PRD rule, not the reverse, so the prose stays verbatim. The internal contrast confirms the reading: where the PRD wants only a prefix constraint (`api_request_id`, lines 30/42) it avoids the word "UUID" entirely.
- **Item 2 (start.sh dependency probe)** — not API behavior. The PRD contains zero startup-probe, dependency-install, or boot-mechanics claims (its only "startup" statement is §2.4's logical-clock initial value, untouched by this change). Step 7 itself classified it as boot-performance only. Nothing to pin.

**Pre-edit search log (candidate edits evaluated, both resolved to no-edit):**

1. **Candidate: resource `id` format.**
   - (a) Subject: format of server-minted resource `id` values.
   - (b) Paths enumerated (full grep of `implementation/`, excluding `__pycache__`): all 13 creation sites mint `"id": str(uuid.uuid4())` — `routes/projects.py:53`, `routes/permits.py:64`, `routes/reaches.py:56`, `routes/plants.py:40`, `routes/plans.py:52`, `routes/surveys.py:70`, `routes/events.py:78`, `routes/monitoring.py:47` (TurbidityReading, the `updated_at`/`version` exception of PRD line 84 — still carries `id`), `routes/monitoring.py:96` (SpeciesSighting), `routes/disposal.py:58` (site), `routes/disposal.py:136` (ticket), `routes/claims.py:93`, `routes/certs.py:100`. The only other uuid use in the codebase is `response.py:11` (`api_request_id = "req_" + uuid.uuid4().hex[:24]`), governed solely by PRD lines 30/42 and satisfied. `error_id` (`errors.py`, `response.py:31-35`) is a catalogue string, not UUID-minted. No input-side UUID parsing/validation exists anywhere (no `uuid.UUID(...)` or regex on path params; ids match by string equality).
   - (c) Wording adjustment: none — no edit committed; existing verbatim prose already covers every enumerated path uniformly.
2. **Candidate: startup probe.**
   - (a) Subject: server startup / dependency-detection mechanics.
   - (b) Paths enumerated: `implementation/start.sh` (only startup artifact; probe now `importlib.util.find_spec('flask')`, install-when-missing contract preserved, `exec python3 app.py`); PRD grep for `start.sh|probe|flask|dependency|boot|startup` matched only §2.4's logical-clock startup value, which the probe change does not touch.
   - (c) Wording adjustment: none — PRD is silent on the subject and the change is non-behavioral, so silence is correct.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/workspace/PRD_FINALIZED.md` (byte-copy of `PRD.md`).

## Step 9: Complete PRD — 2026-08-11T00:58:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1136_dredging_project_operations/workspace/PRD_COMPLETED.md` is written — a minimal in-place patch over PRD_FINALIZED.md.

## Size delta
- PRD_FINALIZED.md: 363 lines, 56,728 chars
- PRD_COMPLETED.md: 363 lines, 60,568 chars (**+0 lines, +3,840 chars** — every change is an inline insert/revision; no new sections or paragraphs)

## Counts
- Ambiguity-pins: **21**
- Mismatch-revisions: **3** (§2.4 clock cascade scope, §2.5 unchanged-refresh write, §3.8 hours precision)
- 24 changes across 21 diff lines (§3.3 holds two pins in one paragraph-line)

## Changes
- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to server wall clock, never the logical clock — response.py:12, util.py:22-25
- §2.2 — insert — ambiguity — routing failures use the same error envelope: unmatched path → 404 `ERR_NOT_FOUND`, wrong method → 405 with `ERR_NOT_FOUND`, unexpected failure → 500 `ERR_INTERNAL` — app.py:47-57
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (to [1,100] / ≥0); non-integer → `ERR_INVALID_REQUEST` 400 — util.py:158-182
- §2.4 — **revise** — **mismatch** — clock-set shutdown cascade fires for every project SUSPENDED after the move, with `shutdown_reason` mapped from the posture derivation cause (WINDOW/TURBIDITY/SPECIES), not only window-exit/WINDOW — services.py:96-108
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — util.py:75-81
- §2.5 — **revise** — **mismatch** — a posture recomputation yielding the unchanged value performs no write (no `updated_at`/`version` bump) — services.py:75-83
- §2.7 — insert — ambiguity — `expected_project_version` is required and must be an integer; missing/non-integer → 400, well-formed stale → 412 — plans.py:133-146
- §2.7 — insert — ambiguity — same pin for `expected_reach_version` — surveys.py:116-129
- §2.9 — revise — ambiguity — class-5 shape pinned: JSON-object body, string/bool/array type checks, integer-only field set (all cent amounts, cy quantities/capacities, NTU values, averaging/stand-down hours, rated production) vs decimal fields (depths, min sounding, bulking factor, claimed hours), naive datetimes read as UTC / offsets converted — util.py:28-40, 94-151
- §2.10 — insert — ambiguity — dredge events also filter by `reach_id` — events.py:110-113
- §3.3 — insert — ambiguity — plan submit only from `DRAFT`/`CHANGES_REQUESTED`; request-changes only from `SUBMITTED`; both else `ERR_INVALID_STATE` — plans.py:89-121
- §3.3 — insert — ambiguity — approval requires the plan itself `SUBMITTED`, else `ERR_INVALID_STATE` — plans.py:152-153
- §3.4 — revise — ambiguity — acceptance supersedes *every* other `ACCEPTED` survey of the same reach+kind (general one-latest rule, covering post-dredge re-acceptance in the deficiency loop) — surveys.py:140-162
- §3.5 — insert — ambiguity — completion (from either posture) clears `shutdown_reason` and `last_shutdown_at` to null — events.py:124-130
- §3.6 — insert — ambiguity — clear-time cooldown fallback: latest-`window_end_utc` `ISSUED` permit when none governs, zero stand-down when no `ISSUED` permit exists — monitoring.py:140-148
- §3.8 — **revise** — **mismatch** — claim hours keep submitted precision; no rounding step applies to `claimed_hours`/`payable_hours` (only the amount is rounded; §3.5 accrual is the only hours rounding) — claims.py:82-90
- §3.9 — insert — ambiguity — unresolvable `standby_claim_ids` element → `ERR_INVALID_REQUEST` 400, same as `reach_ids` — certs.py:79-87
- §3.9 — insert — ambiguity — duplicate `reach_ids` consumed exactly as supplied: per-occurrence pricing lines against the snapshot-time cursor, per-line cursor advance at certification, survey total per occurrence, scow total per unique reach — services.py:188-253, certs.py:177-180
- §3.9 — revise — ambiguity — reconciliation delta = 100 when survey total is zero but scow total is not (PRD pinned only the both-zero case) — services.py:273-276
- §3.9 — insert — ambiguity — `reconciliation_delta_pct` is null on interim certificates — services.py:279
- §3.9 — insert — ambiguity — submission records the caller's `X-User-ID` as `submitted_by_user_id`; a fresh `DRAFT` carries null — certs.py:115, services.py:291
- §3.9 — insert — ambiguity — a non-empty `override_note` at certification is stored on the certificate, from `SUBMITTED` as from `AUDIT_HOLD` — certs.py:221-222
- §3.9 — insert — ambiguity — revision also clears `submitted_by_user_id` and `override_note` — certs.py:248-249
- §4 — insert — ambiguity — dredge-events list endpoint accepts a `reach_id` filter — events.py:110-113

Everything else in the implementation (all 46 endpoints and role assignments, every state-machine transition and terminal-state lock, the posture precedence and trailing-window bounds, production-estimate factors and rounding chain, per-ticket scow rounding and tiered waterfall, OCC/segregation ordering, capacity invariant and FULL↔OPEN flips, ledger compensation on void, close-out gates, error catalogue) matched existing PRD prose uniquely and required no change.
