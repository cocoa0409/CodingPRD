# Worklog — task_1962_school_district_budget_bond_levy_election

## Step 1: Create Task Directory — 2026-08-15T03:17:00.000Z

Directory tasks/task_1962_school_district_budget_bond_levy_election/ and workspace/ already existed (created by pipeline launcher); skipped per instructions.

## Step 2: Generate Scaffold — 2026-08-15T04:22:00.000Z

Scaffold generation complete for task 1962. All three artifacts are written and pass both the mechanical linter and the manual quality gates on the first clean run.

## Generated artifacts

- `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design:`

## Counts

| Element | Count |
|---|---|
| Entities | 16 (FiscalYear, EnrollmentProjection, BudgetVersion, BudgetLine, StaffingAllocation, Position, RevenueEstimate, PublicHearing, Election, BondProposal, BondProject, BallotMeasure, DistrictPublication, BondSale, ProjectExpenditure, CapitalPlanAmendment) |
| State machines | 15 (4 cyclic: BudgetVersion, Position, BondProposal, CapitalPlanAmendment; 1 parallel-dimension: ProjectExpenditure review×payment) |
| Calculations | 17 (2 dual-variant on different domains: state aid vs staffing cost; 3 combinatorial modes a/b/c: staffing FTE formula, per-fund rounding order, pinned PTELL evaluation order) |
| Validations | 13 priority rows (authn → authz → existence → field values → body FKs → OCC → state → safety → temporal → constraint → referential → fiscal) |
| Endpoints | 72 (incl. `POST /_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default) |
| Error codes | 69, all referenced by at least one validation/transition and covered by a test instance or stub |
| Roles | 6 (all opaque; segregation-of-duties model with two SoD pairs) |
| OCC concurrency rules | 2 (budget-version create on FiscalYear.version; bond-sale create on BondProposal.version) |
| §1.8 difficulty instances | 20 (all 9 rules ≥2; rules 2 and 3 carry 3 each) |
| §1.9 corner instances | 78 active + 16 excluded_because stubs (114 unique instance names across both files, zero collisions) |
| Total recipe calls | 1006 |

## Verification results

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (72 endpoints, 16 entities, 20 §1.8 + 78 §1.9 instances, 1006 calls scanned)
- Manual gates (scripted): zero unbound `${var}` placeholders, zero duplicate instance names, all `excluded_because` stubs reference real §1.8 instances, all `grounds` entries resolve (including transition-form refs), no forbidden concurrency vocabulary.
- All numeric asserts pre-computed and machine-verified (e.g., provisional vs certified state aid 13,204,000.00 vs 13,139,200.00; rounding-order-sensitive tax rate 1.7347 vs 1.7346; PTELL cap 8,272,000.00; boundary cases at exactly 200 words, 34,500,000.00 capacity, 14-day buffer, 61-day deadline).

Difficulty-maximizing features per the request: two depth-3 transitive cascades with distinct triggers (adoption: BudgetVersion→StaffingAllocation→Position→FiscalYear aggregates; canvass: Election→BallotMeasure→BondProposal→BondProject), a depth-3 supersede cascade, nested-rounding and pinned-evaluation-order calculations, inclusive/exclusive boundary pairs on seven distinct metrics, dual fiscal gates on expenditures (project budget AND proceeds pool), and cross-FY referential checks — all while keeping every rule implementable and self-consistent against the declared endpoint surface.

## Step 3: Copy Shared Files — 2026-08-15T04:24:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1962_school_district_budget_bond_levy_election/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T04:45:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/workspace/PRD.md`.

## Summary

**Generated**: `PRD.md` (8,610 words, 24 sections: 5 H2 + 19 H3) from the 16-entity / 15-state-machine / 15-calculation / 72-endpoint / 69-error scaffold. The two withheld design files were never opened or referenced.

**Structure** (domain-derived, not template-copied):
- §1 Introduction (2 paragraphs — statutory-calendar framing, `/district` mount, logical clock, segregation of duties)
- §2 (10 subsections): 2.1 RBAC with per-role opaque-identity prose; 2.2 verbatim response-envelope block; 2.3 pagination; 2.4 common properties incl. `DistrictPublication` id+`created_at` exception; 2.5 logical clock & calendar semantics; 2.6 nested retrieval; 2.7 money/rate rounding; 2.8 OCC; 2.9 the 13-stage validation pipeline; 2.10 derived totals & cascades
- §3 (9 subsections, chronological lifecycle grouping): fiscal year/enrollment → budget drafting/transfers → staffing/position control → revenue/PTELL/tax rates → hearings/adoption → bond proposals/project list → elections/canvass → bond sales → expenditures/retainage/amendments
- §4: 72-row endpoint table (4 columns only); §5: 69-row error catalogue (2 columns only)

**Zero-silence coverage check (scaffold §1.1–§1.7 → PRD prose): PASS**
- §1.1: 105/105 entity fields + 63/63 request-body ids + 4/4 query params + 15/15 path params present verbatim in backticks; all defaults, null-until constraints, and enum values (grade bands, fund codes, `REGULAR`/`SPECIAL`, `FACTUAL`/`PROMOTIONAL`, `PRIOR`/`CURRENT`) expressed.
- §1.2: every transition's from/to pair, precondition→error mapping, and side effect (adoption cascade A links 1–3 + fan-out, supersede cascade, canvass cascade B links 1–3, sale-close ledger syncs, void compensation, actor-driven vs cascade version bumps) stated; both OCC rules name `expected_fiscal_year_version`/`expected_bond_proposal_version` + `ERR_STALE_VERSION` (412) without race framing.
- §1.3: all 15 calculations as precise prose — constants embedded (1.00/1.05/1.15, 20/22/25, 40-pupil floor, 0.5 step, 62,000 × 1.34, 7,600 and 2.3%, 5% PTELL CPI cap, 1.8400 rate cap, 6.9% debt limit, 10% retainage, 61/30/10/7/14-day windows, 36-month lapse, 200 words), pinned orders (PTELL five steps, per-fund-round-then-sum), and every boundary (equality-allowed cases, tie-fails, touching-windows rejected) included.
- §1.4: 13-priority pipeline stated globally (§2.9) and restated per multi-check endpoint (hearing hold, adoption, allocation create, sale create, certify, amendment approve).
- §1.0/§1.5: envelope verbatim, pagination defaults (10/1/100/0), `created_at` ascending sort, 201/200 status rules.
- §1.6: all 69 error IDs in §5 with authoritative HTTP statuses and each traceable to a §2/§3 trigger.
- §1.7: all six roles with exact spelling and identity semantics.

**Hard contract reports**: Contract 1 (field coverage) PASS — 105/105, 63/63, 4/4, 15/15, 0 missing. Contract 2 (rule coverage) PASS — 59/59 targeted rule probes present; state pairs, side effects, orderings, and sibling branches all expressed. Contract 3 (§3 path purity) PASS — 590 backtick tokens scanned, 0 paths/methods/combos. No pseudocode operators or fuzzy words found in §1–§3 prose.

## Step 6: Generate Implementation — 2026-08-15T05:00:00.000Z

Implementation complete. Summary:

## File list
- `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/workspace/implementation/app.py` — full Flask server (all logic in one file)
- `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/workspace/implementation/requirements.txt` — `flask>=2.0`
- `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/workspace/implementation/start.sh` — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)

## Endpoint count
**72 endpoints implemented**, matching the scaffold's Table 5 exactly:
- 1 logical clock (`POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z, never falls back to wall clock)
- 5 FiscalYear, 4 EnrollmentProjection, 6 BudgetVersion, 3 BudgetLine/Transfer, 4 StaffingAllocation, 5 Position, 3 RevenueEstimate, 4 PublicHearing, 4 Election, 5 BondProposal, 6 BondProject, 6 BallotMeasure + 2 DistrictPublication, 4 BondSale, 5 ProjectExpenditure, 5 CapitalPlanAmendment

## Key spec fidelity points
- Envelope exactly per scaffold: `meta.api_request_id` (`req_` prefix), `meta.api_request_timestamp` (ISO 8601, 3 fractional digits), `response_type` (`object`/`array`/`error`), `data`; errors use `data.error_id`/`data.message`; pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta` (defaults 10/0, clamp 1–100), lists sorted `created_at` ASC
- Auth: `X-User-ID` + `X-User-Role`, six roles, `ERR_UNAUTHENTICATED` 401 → `ERR_FORBIDDEN_ROLE` 403, validation pipeline ordered auth → RBAC → path 404 (left-to-right) → body shape 400 → semantic 422 → body FK 404 → OCC 412 → state 409 → SoD/prohibited 403 → calendar 409 → uniqueness → referential → fiscal 422
- Calculations via `Decimal` ROUND_HALF_UP: band weights (1.00/1.05/1.15, round to whole pupil), FTE formula (floor 1.0 under 40 pupils, else `ceil((pupils/ratio)*2)/2` with ratios 20/22/25), cost estimates (×62000×1.34 / per-position basis×1.34), PTELL cap in pinned order (request → cap = prior_extension×(1+min(cpi,0.05)) → capped levy → rate check from capped levy vs 1.8400 → total levy), per-fund rates rounded 4dp before summing (sum never re-rounded), state aid `max(0, 7600×weighted − 0.023×eav_basis)` with PROVISIONAL (projected/prior EAV) vs CERTIFIED (certified/current EAV) variants, retainage 10% round-half-up 2dp, bond capacity 6.9% of eav_current
- State machines with full cascades: adoption cascade (allocations DRAFT→AUTHORIZED, positions PROPOSED→OPEN, lines DRAFT→ADOPTED, FY aggregates recomputed, other ADOPTED version superseded), supersede cascade (allocations SUPERSEDED, positions ELIMINATED incl. FILLED, lines SUPERSEDED), canvass cascade (measures PASSED/FAILED strict plurality, proposals REFERRED→PASSED/FAILED with `passed_at`, projects PLANNED→AUTHORIZED with `authorized_amount = estimated_cost`), return-to-draft and FY-close hearing cancellations (no version bump on cascade-cancelled hearings, per PRD §3.5)
- OCC: `expected_fiscal_year_version` on budget-version create, `expected_bond_proposal_version` on bond-sale create → `ERR_STALE_VERSION` 412
- Calendar rules at whole-day UTC granularity: statutory election date (first Tuesday of Mar/Jun/Nov), notice ≥10 days, hold on exact date, adoption window [hearing+7d, FY start), certification ≤ election−61d, campaign window [election−30d, election], canvass strictly after election day, sale_date ≤ passed_at+36 months, close ≥ sale_date; site windows half-open with 14-day buffer (touching = gap 0 = rejected, exactly 14 allowed)
- Storage is in-memory dicts only, **no seeding anywhere** — store starts empty every boot

## Smoke boot result
- `PORT=19999 bash start.sh` → healthy within 3s
- `GET /district/fiscal-years` with Auditor headers → 200, correct envelope, `total_count: 0` (empty store)
- No headers → 401; wrong role on POST → 403; unknown id → `ERR_FISCAL_YEAR_NOT_FOUND` 404
- Clock set → echoes `2026-09-01T00:00:00.000Z`; FY create → 201 DRAFT v1; open → OPEN v2
- Clean `kill` shutdown, then fresh reboot on port 19998 → store confirmed empty again (`total_count: 0`), second clean shutdown

## Step 5: Generate Unit Tests — 2026-08-15T05:30:00.000Z

Generation complete. Summary of what was produced and the audit results:

## Output

**`test_helpers/` (1,835 lines)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/test_helpers/`:
- `types.py` — 22 status/role enums + 16 entity TypedDicts; `DistrictPublication` correctly carries only `id` + `created_at` (append-only, no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with 74 methods covering every PRD §4 endpoint
- `api_errors.py` — `ApiErrorId` (63 codes) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_money`/`assert_rate` (2dp / 4dp tolerances per PRD §2.7)
- `factories.py`, `constants.py` (PTELL/ratios/caps/calendar anchors), `test_users.py` (6 opaque roles + per-role `make_*_headers` builders for segregation-of-duties identity control)
- `fixtures.py` — tiered composites: `setup_draft_budget` → `setup_hearing_held_budget` → `setup_adopted_budget`; `setup_approved_proposal` → `setup_certified_measure` → `setup_passed_proposal` → `setup_closed_sale` → `setup_project_in_progress`; OCC-safe creators that re-read parent versions

**`test_suite/`** — `conftest.py` + 10 test files, **118 tests**, pytest-collected cleanly.

## Coverage (Stage 2 audit, script-verified)

- **Queue A (Difficulty): all 20/20 instances have exactly 2 tests** (40 tests), tagged `Design: Difficulty/<rule_id>/<name>`.
- **Queue B (Corner): 75 of 76 non-stub instances covered** (78 tests; three instances got 2 tests each where the recipe split naturally into success/error envelopes), tagged `Design: Corner/<section>/<name>`.
- **16 `excluded_because:` stubs** not translated; all 16 `difficulty_instance` cross-references verified to resolve.
- **Tag discipline**: every test has exactly one Design line, as the final docstring line, resolving to a real instance; no dangling tags.

## PRD-first adjudication

- **Verbatim citation sweep: 154/154** quoted docstring segments survive literal (whitespace-normalized) grep of PRD.md.
- **No `skip`/`skipif`/`xfail` markers anywhere**; no scaffold references in generated code.

**Skipped instance (1):** `Corner/entities/create_bond_project_extra_field_client_id_ignored_input` — PRD never states whether client-supplied `id`/unknown payload fields are ignored or rejected (§2.9 stage 4 covers only required/type/enum checks); two faithful readers diverge, failing unique derivability.

**Partial-scope adjudications inside covered instances:**
- `staffing_fte_small_band_floor_vs_half_step_ceil`: the YAML's HIGH/800 sub-claim (`required_fte == 36.5`) contradicts the PRD formula (ratio 25 → `ceil((800/25)*2)/2 = 32.0`; the YAML's own arithmetic note is also internally wrong). Tests were emitted for the PRD-clean sub-claims (ELEMENTARY-39 floor = 1.0 with over-allocation rejection; MIDDLE-41 half-step ceil = 2.0); the HIGH/36.5 assertion was dropped, not weakened-into.
- `create_fiscal_year_applies_system_defaults`: asserts PRD-verbatim DRAFT + zeroed aggregates; dropped `version == 1` (initial value never stated in PRD) and `created_at == clock default` (PRD doesn't bind `created_at` to the logical clock).
- `certify_projection_computes_certified_weight` / OCC tests / `immediate_visibility_after_mutation`: assert relative version increments and next-read visibility rather than absolute version numbers or `updated_at` advancement (frozen logical clock makes timestamp-advance non-derivable).
- `notice_publication_date` / `hearing_held_date` asserted by calendar-date prefix, since PRD §2.5's YYYY-MM-DD list omits those two fields (date-vs-timestamp serialization is open design space).

## Step 7: Run Tests and Iterate — 2026-08-15T05:45:00.000Z

**Summary**

- **Iterations run: 2.** Iteration 1: all 8 rounds failed the same 2 tests deterministically (116/118). Iteration 2 (verification sweep): **all 8 rounds 118/118 — clean**.

- **Tests deleted: none.** Both failing tests assert PRD-verbatim, uniquely-derivable rules (§3.7 certification deadline boundary; §3.7/§2.6 canvass completeness + unknown `ballot_measure_id`), so they were kept at full strength.

- **Fixes applied to `test_suite/`** (`/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/test_suite/test_07_elections_ballot_and_canvass.py`):
  - `_two_certified_measures()` (line ~30) and `test_certification_deadline_exact_day_allowed_next_day_rejected` (line ~82) each began with a stray `create_open_fiscal_year()` using the default label "FY2028", immediately followed by `setup_approved_proposal()` which creates a second "FY2028". PRD §3.1 requires "a fiscal year with a unique `label`", so the PRD-faithful implementation correctly rejected the duplicate with `ERR_INVALID_FIELD_VALUE` and the setup raised "Setup step failed with HTTP 422". Both stray calls were dead code (the assigned `fy` was unused / immediately overwritten), so they were removed along with the now-unused import. This is the STEP 2 case: test setup violated a PRD precondition; the implementation's check was kept intact.

- **Fixes applied to `test_helpers/`: none** — fixtures, factories, role-header builders, and assertion helpers were all PRD-consistent.

- **Fixes applied to `implementation/`: none** — `app.py` (2,316 lines, in-memory store, all 63 error codes, both OCC tokens, both cascades) required no changes.

- **Process note:** the iteration-2 sweep's parent shell hit the 10-minute tool timeout mid-run (host shared with other pipeline runs, load ~8); the sweep was relaunched detached via `setsid` with per-round logs and a completion marker, which completed cleanly.

## Step 7b: Orchestrator confirmation sweep — 2026-08-15T05:50:00.000Z

Orchestrator re-ran the 8-round parallel sweep to leave `results.{1..8}.json` evidence on disk in `workspace/implementation/` (the subagent's final sweep logs lived in /tmp and were cleaned up). First two attempts used a start-command without the `cd <impl> &&` prefix that the runner's pytest plugin requires for per-test respawns (`_parse_command` defaults to `.` = repo root otherwise → exit 127, 118 setup errors); corrected to `cd .../workspace/implementation && bash start.sh`. Final result: **all 8 rounds 118/118 passed, 0 failed, 0 errors** — `results.1.json` … `results.8.json` present in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-08-15T05:56:00.000Z

Task complete. `PRD_FINALIZED.md` produced with exactly one targeted insertion.

## Summary

**Line counts / delta:** PRD.md = 401 lines / 65,468 bytes; PRD_FINALIZED.md = 401 lines / 65,581 bytes. Delta: +0 lines, +113 bytes (+0.17%). Single-line diff at line 146.

**Analysis of `<step_7_diff>` items:** Step 7 made zero implementation changes and zero test deletions; the only fixes were removals of dead duplicate-"FY2028" `create_open_fiscal_year()` setup calls in two `test_07` functions. I verified the two kept-at-full-strength tests are fully PRD-determined (§3.7 certification deadline "up to and including the day 61 days before" at line 218; §2.6 line 105 unknown-`ballot_measure_id` → `ERR_BALLOT_MEASURE_NOT_FOUND` and §3.7 line 222 canvass completeness → `ERR_CANVASS_INCOMPLETE`, matching app.py:1493-1512). The one genuine PRD silence the test fix *revealed*: the implementation rejects a duplicate fiscal-year `label` with `ERR_INVALID_FIELD_VALUE` at HTTP 422 (app.py:616-617), while PRD §3.1 stated only "a unique `label`" with no error identity, §2.9 stage 11's uniqueness enumeration omits fiscal-year labels, and §5 has no dedicated error — worse, every other uniqueness error in the catalog is a 409, so a fresh implementer reasoning by analogy would pick the wrong status. This traces directly to the listed `test_suite/` fix (the setups failed with "HTTP 422"), so it is in scope.

**Changes (one bullet per change):**
- §3.1 — insert — added sentence "A create that reuses the `label` of an existing fiscal year is likewise rejected with `ERR_INVALID_FIELD_VALUE`." (HTTP 422 via the existing §5 catalog row) — impl: `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/workspace/implementation/app.py:616-617`.

**Pre-edit search log:**
- (a) Subject: fiscal-year `label` uniqueness — error identity, status, and enforcement surface.
- (b) Impl paths enumerated and read: `create_fiscal_year` (app.py:600-627 — sole enforcement site; check is global across all stored fiscal years regardless of DRAFT/OPEN/CLOSED status, exact string equality, runs immediately after the `end_date>start_date` check, before record creation); `list_fiscal_years` (app.py:630-641 — `label` only an equality filter); `get_fiscal_year` / `open_fiscal_year` / `close_fiscal_year` (app.py:644-694 — read in full; no `label` handling); full route table (63 routes — no PATCH/PUT for fiscal years exists, so create is the only mutation path for `label`); `fy_view` serializer (app.py:259); sibling label-like fields `version_label` (app.py:795, auto-assigned, PRD §3.2) and `series_label` (app.py:1932, 1967-1969 → `ERR_DUPLICATE_SERIES_LABEL` 409, PRD §3.8) plus budget-line `cost_center` (no uniqueness); `test_helpers/fixtures.py:65` (default label "FY2028") and test_02 pagination tests (distinct labels — consistent).
- (c) Wording adjustments: scoped to "a create" (no update endpoint exists); "an existing fiscal year" with no status qualifier (check spans all statuses); no case-sensitivity claim (impl is exact-match, wording stays silent); placed as a standalone sentence after the sibling date-check sentence — mirroring impl check adjacency without interrupting the create-field enumeration, and avoiding any claim about §2.9 pipeline stage 11 (which correctly stays untouched since the impl's error is a 422 semantic-class error, not a 409 uniqueness-class error).

## Step 9: Complete PRD — 2026-08-15T06:15:00.000Z

PRD_COMPLETED.md is complete. Final report:

## Summary

**Source vs output** (both at `/home/ubuntu/github/CodingPRD/tasks/task_1962_school_district_budget_bond_levy_election/workspace/`):
- `PRD_FINALIZED.md` (source): 401 lines, 65,581 chars
- `PRD_COMPLETED.md` (output): 401 lines, 67,032 chars
- Char delta: **+1,451** — all changes are in-paragraph inserts/revisions; no new sections, line count unchanged.

**Counts**: 11 ambiguity-pins, 4 mismatch-revisions (15 changed passages total; the §3.2 budget-version-create edit combines one mismatch revision with one pipeline-order pin).

### Change list (impl = `workspace/implementation/app.py`)

- **§2.3** — insert — ambiguity — Pinned that out-of-range/unparseable `limit`/`offset` are not rejected: `limit` clamps into 1–100, `offset` floors at 0, unparseable falls back to defaults — app.py:112-123
- **§2.4** — revise — ambiguity — Pinned `version` starts at 1 upon creation — app.py:624 (and every other create)
- **§2.8** — revise — mismatch — The fiscal year's `version` advance on budget-version create is unconditional, not tied to supersession ("legitimately supersedes the currently adopted version and advances" → "supersedes any currently adopted version and always advances") — app.py:800-801
- **§3.2** — revise — mismatch — Same unconditional fy-version pin at the workflow site, plus pinned that this create evaluates the fiscal year's `OPEN` gate *before* the OCC token (deviating from §2.9's stage 7-before-8 order; a doubly-failing request surfaces `ERR_FISCAL_YEAR_NOT_OPEN`) — app.py:782-786, 800-801
- **§3.2** — insert — ambiguity — Transfer responds `201 Created` (creation semantics, not a 200 modification) — app.py:983-988
- **§3.2** — revise — mismatch — Return-to-draft from `HEARING_HELD` clears `hearing_held_date` *instead of* sweeping hearings ("additionally" implied both branches sweep; impl sweeps only from `PROPOSED`) — app.py:844-850
- **§3.3** — insert — ambiguity — Allocation `grade_band` ≠ referenced projection's band → `ERR_INVALID_FIELD_VALUE` (previously unnamed error) — app.py:1036-1038
- **§3.3** — insert — ambiguity — Position creation is not gated on allocation state beyond the DRAFT/AUTHORIZED cases; a position under a `SUPERSEDED` allocation is admitted and starts `PROPOSED` — app.py:1119
- **§3.3** — revise — ambiguity — Fill: an *absent* `incumbent_salary` is rejected with `ERR_INVALID_FIELD_VALUE` (422), not the pipeline's stage-4 400 — app.py:1152-1154
- **§3.4** — insert — ambiguity — Revenue-estimate creation has no gate on the budget version's own state — app.py:1252-1291
- **§3.4** — insert — ambiguity — A recertify failing the 1.8400 cap re-check is not rolled back: the provisional freeze and recomputed certified-basis figures persist on the estimate while `status` stays `PROVISIONAL` and `version` is not incremented (impl mutates the stored object before raising) — app.py:1320-1327
- **§3.7** — revise — mismatch — Ballot-measure drafting is not gated on election status ("on a scheduled election" → "on an election — drafting is not gated on the election's status") — app.py:1790-1818
- **§3.7** — insert — ambiguity — Certification's `BOARD_APPROVED` → `REFERRED` pull also increments the proposal's `version` — app.py:1873-1876
- **§3.7** — insert — ambiguity — Canvass entry rules: unknown *or cross-election* `ballot_measure_id` → `ERR_BALLOT_MEASURE_NOT_FOUND`; `yes_votes`/`no_votes` must be non-negative integers else `ERR_INVALID_FIELD_VALUE` — app.py:1493-1506
- **§3.7** — insert — ambiguity — Canvass increments the proposal's `version` in both the PASSED and FAILED cases — app.py:1524-1534

Everything else in the PRD (roles, envelope, clock, rounding discipline, all formulas, state machines, cascades, calendar rules, OCC tokens, error catalogue, endpoint table) was verified line-by-line against the implementation and already pinned uniquely — no further changes needed.
