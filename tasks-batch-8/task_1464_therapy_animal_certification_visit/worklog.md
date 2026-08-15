# Worklog — task_1464_therapy_animal_certification_visit

## Step 1: Create Task Directory — 2026-08-13T09:43:00.000Z

Pre-assigned: `tasks/task_1464_therapy_animal_certification_visit/` and its `workspace/` subdirectory were created externally and handed to this run. No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T11:31:00.000Z

Scaffold generation complete for task_1464_therapy_animal_certification_visit. All three artifacts are written and the lint verdict is clean:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: 16 (Handler, Animal, Team, Evaluator, Evaluation, Certification, VaccinationRecord, Facility, FacilityAgreement, OrientationRecord, InsurancePolicy, LiabilityWaiver, VisitRequest, Visit, IncidentReport, HourCredit as append-only ledger with `common_fields: false`)
- State machines: 16 (Visit's lifecycle × verification split into two parallel-dimension machines; cyclic machines on Certification, VisitRequest, OrientationRecord, Evaluation appeal loop)
- Endpoints: 100 (including `POST /v1/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default and `POST /v1/_sweeps/run` with a pinned 12-phase sweep order)
- Error catalog: 112 codes
- §1.8 difficulty instances: 26 (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear 3, cascade 3, priority-conflict 3, boundary 3, cross-entity 3, overlap 3, invariant 3)
- §1.9 corner instances: 50 (48 active + 2 `excluded_because` stubs), 1501 total calls replayed clean

**Notable design decisions (harder-than-expert calibration)**
- Archetype: compliance/audit × temporal windowing; flat topology with FK links (diversifying away from the all-hybrid examples); peer-role RBAC with entity-backed Handler/Evaluator/FacilityCoordinator identities plus segregation-of-duties on incident triage-vs-resolve (`ERR_SOD_VIOLATION`).
- Dual-variant calcs in distinct domains: visit hour credits (PROVISIONAL scheduled-minutes vs FINAL clamped-and-rounded, reconciled via REVERSAL rows) and animal welfare workload (FORWARD_LOOKING vs AUDIT windowing, AUDIT pinned closed-at-now).
- Combinatorial coverage: mode (a) `team_match_score` with nested min/max, priority multipliers and a NURSING_HOME exclusion branch; mode (b) per-credit-then-sum 15-minute rounding pinned against sum-then-round (30 vs 15 divergence); mode (c) renewal order-of-operations pinned (`max(today, old_expires_on) + 730d`, eligibility counted against the pre-renewal window) with literal date asserts (2030-08-01 vs 2030-07-02).
- Cascade triggers differentiated by origin: incident-escalate (depth 4), insurance-cancel (depth 3, and policy *expiry* explicitly non-cascading), agreement-termination with pinned visits-then-requests ordering (reopened requests land WITHDRAWN).
- Three distinct interval semantics: team half-open (adjacency allowed), evaluator 30-minute buffered (adjacency conflicts, gap ≥ 30 passes), facility aggregate overlapping-count capacity.
- Two OCC rules (`offer-create-stale-request`, `visit-create-stale-team`), with OCC checked at priority 6 ahead of state at 7 — one corner instance asserts the stale-version error wins over `ERR_REQUEST_NOT_OPEN`.
- Validation stack pinned 1–13 (auth → ownership → existence → schema → OCC → state → safety → referential → temporal → fiscal → constraint → SoD) with three conflict-pair instances on distinct category pairs.
- Two self-consistency bugs found and fixed during replay: species removed from match-score eligibility (kept as a scoring input so the 67.5/30.0 divergence is observable), and the renewal instance's facility weekly cap raised to 8 so 6 same-week visits are legal.

## Step 3: Copy Shared Files — 2026-08-13T11:32:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1464_therapy_animal_certification_visit/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T11:47:00.000Z

All verification passes are green. PRD generation is complete.

**Output written:** `workspace/PRD.md` — 465 lines.

**Section list:**
- §1 Introduction (2 paragraphs, pain-point/business-context angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified), 2.3 Pagination, 2.4 Logical Clock & Deterministic Sweeps, 2.5 Common Resource Properties (incl. HourCredit exception), 2.6 OCC, 2.7 Validation Pipeline & Check Ordering (13 priorities), 2.8 Bubble-Up & Cascade-Down Consistency, 2.9 Volunteer Hour Ledger, 2.10 Units/Precision/Rounding
- §3 Business Logic (9 subsections): 3.1 Handlers/Animals/Teams, 3.2 Evaluations & Scoring, 3.3 Certification Issuance/Renewal/Discipline, 3.4 Facilities/Agreements/Orientation/Waivers, 3.5 Insurance & Adequacy, 3.6 Visit Requests & Candidate Matching, 3.7 Scheduling & Conducting a Visit, 3.8 Verification/Disputes/Recognition, 3.9 Incidents & Welfare Enforcement
- §4 Endpoint Definitions — 100 rows, 4 columns, path/method sequence verified identical to scaffold
- §5 Error Code Catalogue — 114 rows, 2 columns, no trigger conditions

**Hard Contract reports:**
- Contract 1 (Field-Name Coverage): entities+endpoint inputs+query/path params — 115 required, 115 present, 0 missing; output-only fields (sweep counts, recognition/demand summaries) 24/24 present. **PASS**
- Contract 2 (Rule Coverage): 2/2 OCC rules with endpoint+field+`ERR_STALE_VERSION`/412; all state-machine transitions with preconditions+side-effects; all 11 calculations reconstructed in operator-free prose (65-point spot audit incl. pinned renewal order, at-posting rounding pin, cascade hop enumerations, sibling-branch density) — 0 missing. **PASS**
- Contract 3 (§3 Path Purity): 888 backtick tokens scanned (code fences stripped), 0 path/method violations. **PASS**

**Zero-Silence Rule decisions (scaffold gaps resolved explicitly):**
1. `ERR_EVALUATOR_SPECIES_MISMATCH` and `ERR_POLICY_WINDOW_INVALID` are nominated by state-machine preconditions (SCAFFOLD lines 434, 813) but absent from the §1.6 catalog — both are named in §3.2/§3.5 prose and included in the §5 table at 409 Conflict (the state-precondition status for those endpoints), hence 114 rows vs 112 catalog entries.
2. Facility overlap capacity (`max_overlapping_teams`): scaffold silent on which visit states count — PRD states the rule exactly as scaffolded ("visits whose scheduled intervals overlap at any instant") without inventing a state filter.
3. Recognition output `next_tier`/`minutes_to_next_tier`: PLATINUM-edge behavior unspecified — described generically ("the next higher tier", "additional minutes needed"), no invented terminal behavior.
4. Free-text `reason` payloads: described as carried by the call; stated as persisted only where the scaffold stores them (`suspension_reason`, `terminated_reason`, HourCredit `note`).
5. Handler `email` uniqueness and per-handler `policy_number` uniqueness: stated as constraints without pinning an error ID (the catalog dedicates none; they fall under body-schema validation).

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, and no sibling task directories were inspected.

## Step 6: Generate Implementation — 2026-08-13T12:36:00.000Z (RESUME RECOVERY)

The prior run was terminated after writing the implementation but before logging this step. On resume, the orchestrator verified the existing `workspace/implementation/` artifact rather than regenerating it: all 32 Python files (app.py entry point, db/errors/middleware/response/util/validate/constants core modules, 17 route blueprints covering all 16 entities + admin clock/sweep endpoints, 6 service modules) compile cleanly under `py_compile`; `start.sh` is present, executable, installs flask only when missing, and execs `python3 app.py` in the foreground reading `$PORT` and binding `0.0.0.0`; a live boot smoke test on a scratch port succeeded (server started, request routed, auth-missing 400 returned as designed). Implementation kept and reused as-is.

## Step 5: Generate Unit Tests — 2026-08-13T12:52:00.000Z

Generation complete. All deliverables are in place and the full audit battery passes.

**`test_helpers/`** (9 files):
- `types.py` — all 16 entity TypedDicts + status/role enums; `HourCredit` correctly modeled as append-only (no `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (70+ methods, all `/v1` routes incl. `_clock`/`_sweeps`)
- `api_errors.py` — all 106 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_instants_equal` (representation-safe instant comparison), `assert_ledger_consistency`
- `factories.py` — payload factories with unique emails/policy numbers
- `constants.py`, `test_users.py` (opaque vs entity-backed role headers + `make_*` builders)
- `fixtures.py` — the load-bearing composite chain: `setup_certified_team` (handler→animal→team→evaluation→PASSED→rabies→ACTIVE policy→certification ACTIVE), `setup_active_facility` (agreement handshake), `setup_visit_ready_team`, `setup_certified_team_at_facility`, visit lifecycle helpers, offer/accept helpers, `setup_renewable_certification` (six COMPLETED+VERIFIED visits), incident helpers — all threading entity-backed identity via `make_*_headers(real_id)`

**`test_suite/`** — `conftest.py` + 11 numbered test files, **100 tests**: 52 difficulty (26 instances × 2) + 48 corner (all non-stub instances).

**Audit results**
- Coverage: every §1.8 instance has exactly 2 tagged tests; every non-stub §1.9 instance has 1; both `excluded_because` stubs (`waiver_void_blocks_new_visits`, `recognition_summary_computed_read`) correctly untranslated with verified cross-references
- Every docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag; no dangling tags
- All 158 quoted PRD citation lines survive literal grep against `PRD.md`
- No `skip`/`xfail`, no scaffold references, all files compile, `pytest --collect-only` collects 100 tests

**Judgment calls (worth the caller's attention)**
- **`recognition_tier_exact_threshold`**: the design recipe's expected `tier0 == NONE` at 5985 minutes contradicts the PRD tier table (`BRONZE` at 1500 inclusive). I translated with the PRD-derived expectation (5985 → BRONZE, `next_tier` SILVER, `minutes_to_next_tier` 15) while preserving the instance's load-bearing claim (exactly 6000 → SILVER, inclusive).
- **Initial `version` value** is not pinned by the PRD ("increments with every mutation"), so assertions use relative form (`v_approve == v_create + 1`, no drift) instead of the recipe's absolute `== 1`/`== 2`.
- **Datetime assertions** compare parsed instants, not raw strings (PRD pins three-fractional-digit instants; string equality would be brittle).
- **Orientation recipe repair**: `orientation_expiry_reassign_cycle` omitted a clock advance before completing orientation with `attended_on` 2026-08-02 (would hit `ERR_ORIENTATION_DATE_FUTURE` at the 2026-08-01 default clock); the translation inserts `set_clock("2026-08-02T00:00:00Z")` per the PRD's `ERR_ORIENTATION_DATE_FUTURE` rule.
- **Multi-team clock staggering**: tests building several certified teams in one scenario (hospital multiplier, facility capacity, match score) pass explicit later `eval_start`/`eval_end` slots so each chain's evaluation isn't in the past after the prior chain advanced the logical clock.

## Step 6: Diagnostic iteration — 2026-08-13

8-round parallel stability sweep #1 (`--isolation per-test-server`): 97/100 in every round; 3 deterministic failures (identical in all 8 rounds — no flakiness).

Diagnoses and fixes (PRD-first protocol):

1. `test_fiscal_failure_isolated_on_renewal` (expected `ERR_NO_ACTIVE_INSURANCE`, got `ERR_RENEWAL_VISIT_MINIMUM_NOT_MET`) — IMPLEMENTATION BUG. PRD §2.7 pipeline puts fiscal adequacy (category 11) before capacity/uniqueness/minimums (category 12). `routes/certifications.py::renew_certification` ran the visit-minimum count before the insurance check. Reordered to pipeline order: state (7) → rabies safety (8) → late-renewal window (10) → insurance floor (11) → visit minimum (12). (The pre-existing window-vs-rabies misorder — 10 before 8 — was corrected in the same edit.)
2. `test_suspended_certification_blocks_visit_creation` (expected `ERR_CERT_NOT_ACTIVE`, got `ERR_TEAM_NOT_ACTIVE`) — TEST BUG. PRD §3.3 suspension cascade drops the team `ACTIVE → SUSPENDED` in step, and §2.7 checks team state (category 7, `ERR_TEAM_NOT_ACTIVE`) before the certification referential gate (category 9, `ERR_CERT_NOT_ACTIVE`), so the suspended-cert scenario deterministically yields `ERR_TEAM_NOT_ACTIVE` under any PRD-faithful implementation. The only PRD path to cert-not-active with the team still ACTIVE is sweep-driven EXPIRY (no cascade). Rewrote the test (`test_suite/test_08_visit_cert_gates_and_checkin.py`) as `test_expired_certification_blocks_visit_creation`: `setup_renewable_certification` → clock past `expires_on` + sweep → cert EXPIRED / team ACTIVE → visit create rejected `ERR_CERT_NOT_ACTIVE` → renewal inside the 90-day grace (6 verified visits in term) restores ACTIVE → orientation re-assign/complete cycle covers the new date → identical payload succeeds with 201 SCHEDULED. Design tag preserved. Supporting helper change: `test_helpers/fixtures.py::setup_renewable_certification` gained an optional `facility_kwargs` passthrough (needed a long-lived agreement); default behavior unchanged.
3. `test_escalation_cancels_visits_and_reopens_requests` (expected `cancel_reason INCIDENT_PRECAUTION`, got `CERT_SUSPENDED`) — IMPLEMENTATION BUG. PRD §3.9 verbatim: on escalation "every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `INCIDENT_PRECAUTION`". `services/cascades.py::incident_escalation_cascade` delegated to `suspend_certification`, which hardcoded `CERT_SUSPENDED` for visit cancellation. `suspend_certification` now takes `visit_cancel_reason` (default `CERT_SUSPENDED`); the escalation cascade passes `INCIDENT_PRECAUTION`.

No tests deleted; no assertions weakened.

## Step 7: Run Tests and Iterate — 2026-08-13T13:15:00.000Z

Clean 8-round parallel sweep achieved: all 8 rounds at 100/100 passed.

**Summary**

- **Iterations run:** 2 (sweep 1: 97/100 in every round with 3 deterministic failures; sweep 2 after fixes: 100/100 × 8 rounds, zero failures, zero flakiness).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/fixtures.py` — `setup_renewable_certification` gained an optional `facility_kwargs` passthrough (merged over the default `{"visits_per_week_cap": 8}`), needed so a test can request a long-lived agreement; default behavior unchanged.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_08_visit_cert_gates_and_checkin.py` — `test_suspended_certification_blocks_visit_creation` rewritten as `test_expired_certification_blocks_visit_creation`. TEST BUG (STEP 2): the old setup suspended the certification, but PRD §3.3's suspension cascade drops the team to SUSPENDED in step, and PRD §2.7's pipeline checks team state (category 7, `ERR_TEAM_NOT_ACTIVE`) before the certification referential gate (category 9, `ERR_CERT_NOT_ACTIVE`) — so the old scenario deterministically yields `ERR_TEAM_NOT_ACTIVE` in any PRD-faithful implementation. The rewrite isolates the cert gate via the only PRD path that leaves the team ACTIVE with a non-active cert: sweep-driven EXPIRY (no cascade), then recovers via renewal inside the 90-day grace plus an orientation re-assign/complete cycle. The `ERR_CERT_NOT_ACTIVE` assertion and design tag are preserved.

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes/certifications.py` — `renew_certification` reordered to the PRD §2.7 pipeline: state (7) → rabies safety (8) → late-renewal window (10) → insurance floor (11) → visit minimum (12). Previously the visit-minimum check (12) ran before insurance (11), so a lapsed policy surfaced `ERR_RENEWAL_VISIT_MINIMUM_NOT_MET` instead of `ERR_NO_ACTIVE_INSURANCE`; the window-vs-rabies misorder (10 before 8) was corrected in the same edit.
  - `workspace/implementation/services/cascades.py` — `suspend_certification` now takes `visit_cancel_reason` (default `CERT_SUSPENDED`), and `incident_escalation_cascade` passes `INCIDENT_PRECAUTION`, matching PRD §3.9's verbatim requirement that escalation-cancelled visits carry `cancel_reason` `INCIDENT_PRECAUTION`.

No assertions weakened, no implementation checks removed, no data seeded.

## Step 8: Finalize PRD — 2026-08-13T13:35:00.000Z

PRD_FINALIZED.md is written with exactly one in-place revision.

**Line counts:** PRD.md = 465 lines, PRD_FINALIZED.md = 465 lines — 0% delta (one line revised in place; nothing added or removed).

**Changes:**
- §3.3 — revise — the suspension-cascade sentence now reads "every `SCHEDULED` visit of the team is cancelled with `cancel_reason` `CERT_SUSPENDED` (the incident-escalation cascade of §3.9 instead stamps `INCIDENT_PRECAUTION`, as specified there)" — traces to step_7_diff's `cascades.py` fix; impl: `workspace/implementation/services/cascades.py:61-62` (default `visit_cancel_reason="CERT_SUSPENDED"`) and `:204-205` (escalation passes `INCIDENT_PRECAUTION`).

**Step-7 items that required no edit:**
- `fixtures.py` `facility_kwargs` passthrough — pure test-helper plumbing (lets a test request a longer agreement); touches no impl behavior and reveals no PRD silence.
- `test_08` rewrite (suspended → expired cert gate) — pure test bug. Everything the rewrite relies on is already PRD-pinned: §3.3 drops the team in step on suspension, §2.7 orders state (cat. 7, `ERR_TEAM_NOT_ACTIVE`) before referential (cat. 9, `ERR_CERT_NOT_ACTIVE`), and cert expiry has no cascade (§2.8's closed trigger list excludes expiry; §3.1's team mirror names only activation/suspension/reinstatement; confirmed `sweeps.py:99-104` leaves the team ACTIVE).
- `renew_certification` reorder — an impl bug fixed to *conform* to §2.7, which already uniquely pins the renewal order 7→8→10→11→12 (each category's "Applies to" explicitly covers renewal). Current impl `certifications.py:117-157` matches the PRD verbatim, so the prose stands.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: the `cancel_reason` stamped on `SCHEDULED` visits cancelled by a certification-suspension cascade — which triggers yield `CERT_SUSPENDED` vs `INCIDENT_PRECAUTION`.
- (b) Impl paths enumerated and read/grepped: `routes/certifications.py:160-173` (manual suspend → default CERT_SUSPENDED); `routes/visits.py:194-215` (late-cancel threshold → `LATE_CANCELLATIONS` with default visit reason); `routes/policies.py:107` → `services/cascades.py:162-177` (insurance-lapse → default CERT_SUSPENDED, also §3.5-explicit); `services/cascades.py:61-81` (the default parameter itself); `services/cascades.py:184-210` (escalation → `INCIDENT_PRECAUTION`, both the cert-suspension branch at :204-205 and the no-cert defensive branch at :210); `services/cascades.py:248-265` (§3.9 SUSPENSION-resolution path → `CERT_SUSPENDED` at :261). Non-suspension cancel paths (`CERT_REVOKED` :92/:271, `TEAM_DISSOLVED` :126, `AGREEMENT_ENDED` :141, actor-mapped reasons at `visits.py:183-191`) confirmed outside the edit's sentence. PRD cross-references checked: §2.8, §3.5, §3.7 (system-cause list already includes `INCIDENT_PRECAUTION`), §3.9.
- (c) Wording adjustment: the carve-out was deliberately scoped to "the incident-escalation cascade of §3.9" only, so the manual, insurance-lapse, late-cancel, and SUSPENSION-resolution paths all remain under the blanket `CERT_SUSPENDED` statement — no enumerated path is mis-described, and no other cascade sentence was narrowed.

## Step 9: Complete PRD — 2026-08-13T15:10:00.000Z

All passages verified coherent. PRD_COMPLETED.md produced.

**Source vs output:** `PRD_FINALIZED.md` (465 lines) → `PRD_COMPLETED.md` (466 lines, +1), char-delta **+3379**, 23 diff hunks covering 34 distinct pins/revisions.

**Counts:** 29 ambiguity-pins, 5 mismatch-revisions.

### Mismatch revisions (5)
- §2.4 — revise — mismatch — "The server never consults wall-clock time" contradicted impl, which renders the envelope `api_request_timestamp` from wall-clock; carved out that sole exception — `implementation/response.py:14-17`
- §3.1 — revise — mismatch — "Once approved, a handler registers animals" implied a status gate impl never enforces; pinned that registration carries no handler-status gate — `implementation/routes/animals.py:24-47`
- §3.1 — revise — mismatch — `welfare_blocked_until` "null when no rest is owed": impl nulls it only before the first completed visit and retains stale expiries thereafter — `implementation/routes/visits.py:150-152`, `implementation/routes/animals.py:43`
- §3.4 — revise — mismatch — "the four operating rules" miscounted five listed fields; corrected to five and pinned numeric rules as non-negative integers — `implementation/routes/facilities.py:47-62`
- §3.5 — revise — mismatch — "a `policy_number` unique per handler" was never enforced; pinned as recorded-as-supplied with no uniqueness check — `implementation/routes/policies.py:29-47`

### Ambiguity pins (29)
- §2.2 — insert — undefined route/method → `ERR_NOT_FOUND` (404); internal fault → `ERR_INTERNAL` (500), same envelope — `implementation/app.py:37-47`
- §2.3 — insert — malformed/out-of-range `limit`/`offset` are clamped to defaults/bounds, never rejected — `implementation/response.py:63-87`
- §2.3 — insert — `created_at` sort ties break by creation order — `implementation/response.py:90-96`
- §2.4 — insert — startup clock value renders without fractional digits until first set — `implementation/db.py:15`, `implementation/services/records.py:10`
- §2.4 — revise — clock capability "advances" → sets (offsets normalized to UTC, no monotonicity check) — `implementation/routes/admin.py:18-20`
- §2.5 — insert — `version` starts at 1; `created_at`/`updated_at` stamped from the logical clock — `implementation/services/records.py:10-12`
- §2.7(5) — insert — declared numeric ranges (scores 0–100, evaluator cap 1–8, suspension_days 1–365) and non-empty list rules are `ERR_INVALID_REQUEST` schema checks — `implementation/routes/evaluations.py:172-174`, `evaluators.py:17-29`, `incidents.py:127-131`, `facilities.py:28-40`
- §2.7(8) — revise — category-8 scope pinned: full for scheduling/acceptance, rabies-only for cert activation/renewal/reinstatement, hold-only for check-in — `implementation/routes/certifications.py:105,129,189`
- §2.10 — insert — an instant exactly equal to now is never "in the past" — `implementation/services/gates.py:198`, `routes/requests.py:44`, `routes/evaluations.py:120`
- §3.1 — insert — duplicate handler email fails `ERR_INVALID_REQUEST` — `implementation/routes/handlers.py:36-38`
- §3.1 — revise — team-formation payload carries both `animal_id` and `team_name` — `implementation/routes/teams.py:27-30`
- §3.1 — insert — dissolving an already `DISSOLVED` team fails `ERR_TEAM_NOT_ACTIVE` — `implementation/routes/teams.py:84-86`
- §3.2 — insert — rescheduling out of `APPEALED` retains the prior attempt's scores until re-scored — `implementation/routes/evaluations.py:152-158`
- §3.2 — insert — scoring checks `SCHEDULED` state before the ownership gate — `implementation/routes/evaluations.py:175-178`
- §3.3 — insert — renewal returns the certification to `ACTIVE` — `implementation/routes/certifications.py:153`
- §3.6 — insert — experience year = 365 days, contribution floored at zero — `implementation/services/scoring.py:83-87`
- §3.6 — insert — recency measured from the visit's `verified_at` instant — `implementation/services/scoring.py:98-112`
- §3.6 — insert — candidate slate entries are full team objects augmented with `score`, returned in one unpaginated page — `implementation/routes/requests.py:192-197`
- §3.6 — insert — offer acceptance answers `200 OK` carrying the created visit — `implementation/routes/requests.py:146-149`
- §3.6 — insert — withdrawal retains the offer fields (cleared only on return to `OPEN`) — `implementation/routes/requests.py:171-183`, `services/cascades.py:142-145`
- §3.7 — insert — workload window placement: `SCHEDULED`/`IN_PROGRESS` by `scheduled_start`, `COMPLETED` by `actual_end` — `implementation/services/credits.py:144-177`
- §3.7 — insert — workload changes are wholesale recomputes; out-of-window bookings/cancellations leave the stored figure unchanged — `implementation/services/credits.py:180-186`
- §3.7 — insert — facility overlap capacity counts only `SCHEDULED`/`IN_PROGRESS` visits, half-open intervals — `implementation/services/gates.py:242-264`
- §3.7 — insert — weekly cap places each visit in the ISO week of its `scheduled_start` — `implementation/services/gates.py:226-237`
- §3.7 — insert — visit-cancel accepts an optional `reason` field that is not recorded; `cancel_reason` derives only from actor/cascade — `implementation/routes/visits.py:171,183-188`
- §3.7 — insert — late-cancel counter resets at threshold whether or not a certification stood to be suspended — `implementation/routes/visits.py:206-215`
- §3.8 — insert — deemed-verified sweep stamps `verified_at` — `implementation/services/sweeps.py:139-143`
- §3.8 — insert — PLATINUM handler: `next_tier` null, `minutes_to_next_tier` 0 — `implementation/routes/handlers.py:154-159`
- §3.9 — insert — `SUSPENSION` resolution: `suspension_until` is the calendar date today+days; animal hold set only when currently on hold (now+days); §3.3 suspension cascade fires when the cert was not already suspended — `implementation/services/cascades.py:248-265`

**Notable non-changes (verified already pinned):** the full visit-gate chain order in §2.7/§3.7 matches `gates.run_visit_gates` exactly, including the subtlety that a welfare-held animal at scheduling surfaces `ERR_ANIMAL_NOT_ACTIVE` (category 7) rather than the unreachable category-8 hold check — PRD's pinned ordering already entails this. Sweep order/keys, OCC scope, late-cancel tiers, rounding rules, match-score formula, and all endpoint/role rows in §4 matched implementation with no edit needed.
