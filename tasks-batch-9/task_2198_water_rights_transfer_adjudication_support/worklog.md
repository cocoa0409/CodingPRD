# Worklog — task_2198_water_rights_transfer_adjudication_support

## Step 1: Create task directory — 2026-08-31T17:54:42.824Z

Created `tasks/task_2198_water_rights_transfer_adjudication_support/` and `tasks/task_2198_water_rights_transfer_adjudication_support/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 1b: Resume-mode audit — 2026-09-01T02:36:00.000Z

RESUME MODE entered. Audited task directory on disk: only `worklog.md` (5 lines, Step 1 entry) and an empty `workspace/` existed. No SCAFFOLD.yaml, no SCAFFOLD_DIFFICULTY_DESIGN.yaml, no SCAFFOLD_CORNER_DESIGN.yaml, no workspace/INSTRUCTION.md, no workspace/PRD.md, no test_helpers/, no test_suite/, no workspace/implementation/, no PRD_FINALIZED.md, no PRD_COMPLETED.md. First incomplete step = Step 2. Pipeline resumed from Step 2 with the scenario description passed verbatim; task directory name preserved.

## Step 2: Generate scaffold — 2026-09-01T02:36:00.000Z

Step 2 ran as one long-lived subagent resumed across three bounded turns (SCAFFOLD.yaml, then SCAFFOLD_DIFFICULTY_DESIGN.yaml, then SCAFFOLD_CORNER_DESIGN.yaml) because a single-turn attempt was killed by an API timeout before writing any file. Subagent summaries verbatim below.

### Turn 1 — SCAFFOLD.yaml

`SCAFFOLD.yaml` is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2198_water_rights_transfer_adjudication_support/SCAFFOLD.yaml` (4,222 lines, §1.0–§1.7 only — no `scaffold_difficulty_design` / `scaffold_corner_design` key; verbatim scenario string and the fixed §1.0 envelope copied unmodified).

It emits **13 entities** (Claimant, WaterRight, PointOfDiversion, BeneficialUseRecord — the one `common_fields: false` append-only evidence row, HcuStudy, TransferApplication, InjuryAnalysis, Protest, ApprovalCondition, WaterBankAccount, LeaseAssignment, DecreeDocket, AdjudicationClaim) in a `graph` topology; **12 state machines over 10 entities** (two cyclic — TransferApplication revision rounds and LeaseAssignment ACTIVE↔SUSPENDED; two parallel-dimension pairs — ApprovalCondition status×payment_status and AdjudicationClaim filing_status×verification_status; one branching fork-join — Protest NEGOTIATION vs HEARING track converging on RESOLVED_STIPULATED with divergent side effects; one compound/bubble-up — DecreeDocket phase), plus four named transitive cascades (condition-violation, protest-clearance, fee-payment, forfeiture) of depth 3–4; **3 §1.2.1 OCC rules** (`hcu-certify-stale-right`, `application-submit-stale-right` on `expected_water_right_version` → ERR_STALE_RIGHT_VERSION; `bank-deposit-stale-account` on `expected_water_bank_account_version` → ERR_STALE_ACCOUNT_VERSION); **12 calculations** of which 3 are dual-variant (hcu_transferable_volume DIVERSION_BASED/CIR_BASED, injury_net_analysis INSTANTANEOUS/SEASONAL, lease_settlement_credit PRO_RATA_DAILY/SEASON_BLOCK) and 2 are conserved-quantity ledgers (right_volume_ledger, bank_credit_ledger), alongside a half-open POD rate aggregation vs a closed+7-day-buffer lease exclusivity window; **49 priority-ordered validations** (auth 1–5, shape 6, existence/FK 7, referential 8–10, uniqueness 11–14, OCC 15–16, state 17–22, safety 23–31, temporal 32–36, constraint 37–44, fiscal 45–48, referential child-gate 49) with three deliberate priority-conflict pairs (temporal 32 over constraint 39 on protest filing, constraint 41 over fiscal 46 on lease creation, safety 24 over fiscal 45 on submit); **65 endpoints** (all `code:`-tagged, list-form `input:` with `?` optionals, `output:` in canonical `Entity`/`Entity[]` form except two genuine computed reads, `api_prefix: "/"`, every placeholder literally `{id}`, plus the mandatory `POST /_clock/set_current_utc` documenting the `2026-08-01T00:00:00Z` startup default); **58 error codes** in §1.6 — verified to be exactly the set raised by §1.5, no orphans in either direction; and **5 roles** in §1.7 (`Claimant` as `entity_backed:Claimant`, plus opaque WaterRightsAnalyst / HearingOfficer / DecisionAuthority / BasinAdjudicator) under a segregation-of-duties model where each role holds at least one exclusive operation and the certifier/protest-resolver user ids structurally bar the decider.

Two verification notes: I ran `scaffold_lint.py`'s FK reverse-reachability check (f) directly against the file — 0 violations, all 12 collection segments derived — and confirmed `load_endpoints` parses all 65 cleanly, so the `input:`/`output:` shapes are lint-compatible ahead of the §1.8/§1.9 pass. Per instruction I have not started `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`; full-suite lint will only pass once those exist.

### Turn 2 — SCAFFOLD_DIFFICULTY_DESIGN.yaml

`/home/ubuntu/github/CodingPRD/tasks/task_2198_water_rights_transfer_adjudication_support/SCAFFOLD_DIFFICULTY_DESIGN.yaml` is written (2,221 lines, single top-level key `scaffold_difficulty_design`), built up over seven successive Write/Edit calls. It carries **20 non-stub instances with no stubs and no `excluded_because` entries**, distributed as: `dual_variant_calc` 2 (HCU DIVERSION_BASED 132.98 vs CIR_BASED 210.00 on identical records; lease settlement PRO_RATA_DAILY 20.00/40.00 vs SEASON_BLOCK 30.00/30.00 — different entity domains), `combinatorial_formula` 2 in **different modes** (mode (c): mitigation tier read from the pre-surcharge subtotal, 4987.50 → 0.040 → 5187.00 versus the wrong direction's 5336.63; mode (b): round-per-year-then-average 75.134/75.13 versus sum-then-round 75.135/75.14), `non_linear_state_machine` 2 on different entities (TransferApplication revision cycle back into SUBMITTED with revision_round 1, escrow swap 100.00 ≤ 135.00+60.00 and a 15-day rather than 30-day republication deadline; Protest FILED fork to NEGOTIATION → offset 10.00/net 29.10/zero conditions versus HEARING → offset 0.00/net 39.10/one HEARING_RESOLUTION condition), `transitive_cascade` 2 with different triggers (condition-violation chain of 5 observable links ending in account posture FROZEN and score 60.50→72.50; last-protest-resolution chain ending in FINALIZED analysis at offset 12.50/net 34.30, with the first resolution asserted as a negative control), `priority_pair_validation_conflict` 3 on different category pairs (temporal 32 over constraint 39; constraint 41 over fiscal 46; safety 24 over fiscal 45 — each with a control call that yields the loser's error), `boundary_precision_check` 3 (POD rate equality 3.000 accepted / 3.001 rejected; empty-qualifying-set 422 plus the strict `<` haircut boundary 165.75 vs 195.00; the inclusive 5-consecutive-non-use-year forfeiture boundary, 33.50/LOW/422 vs 42.50/ELEVATED/200), `cross_entity_state_dependency` 2 (lease activation gated on WaterBankAccount.posture at available 4.00 < 5.00; claim examination gated on DecreeDocket.phase with two different refusal codes), `resource_temporal_overlap` 2 with genuinely different geometries (half-open adjacency + conservative rate aggregation at one headgate; closed 7-day fallow buffer across headgates, both boundary edges 2026-07-07/2026-07-08 and 2026-03-25/2026-03-24), and `compensating_invariant` 2 on different conserved quantities (right volume ledger under submit/withdraw; bank credit ledger under reserve/cancel-from-RESERVED, including the trap where booking requested_af instead of used_af loses 25.00 af of the parent right).

Every `grounds:` reference was machine-verified to resolve into SCAFFOLD.yaml, every `${var}` is bound by an earlier `captures:`, no `expected_*_version` is a literal, and all numeric asserts were computed with `decimal.Decimal`/`ROUND_HALF_UP` against the §1.3 formulas. `scaffold_lint.py` run against SCAFFOLD.yaml + this file (with an empty stand-in corner file) reports **VERDICT: clean lint** over 325 scanned calls. One incidental fix in SCAFFOLD.yaml: the `GET /water-rights/{id}/forfeiture-assessment` output declared `forfeiture_risk_score` and the two fractional components as `integer`; they are now `number` with the pinned precisions. SCAFFOLD_CORNER_DESIGN.yaml has not been started, as instructed.

### Turn 3 — SCAFFOLD_CORNER_DESIGN.yaml + full lint

`SCAFFOLD_CORNER_DESIGN.yaml` is written (3,896 lines) and the full three-file lint is clean.

**Per-section instance counts (§1.9, 114 instances total, 89 non-stub / 25 `excluded_because` stubs):** entities 17 (17/0), state_machines 26 (24/2), calculations 20 (12/8), validations 13 (10/3), endpoints 6 (6/0), errors 17 (8/9), rbac 5 (5/0), cross_cutting_complexity_layers 8 (5/3), consistency_model 2 (2/0). Claim types are drawn only from the guide's per-section rows; every applicable row is exercised (entities also covers `topology`; calculations covers `reconciliation` via the two ledger-conservation stubs; state_machines covers `initial_state` with the counter-intuitive "POD created after activation still enters PROPOSED / new bank account enters RESTRICTED, not OPEN" instance). The only guide row deliberately unused is endpoints→`bulk_action`, because §1.5 declares no bulk endpoint.

**Deliberate stubs** (all cite a §1.8 instance by name, all verified to exist, and each stubbed error id is positively asserted there): 8 calculations stubs (HCU correct-result/qualifying set, mitigation-fee tier order, lease-settlement variant, POD rate load, lease exclusion window, and the two ledger-conservation identities), 3 validation-ordering stubs (protest deadline > duplicate protest, lease window conflict > insufficient credit, standing sanction > volume budget), 2 cascade stubs (condition-violation suspension, protest-clearance finalization), 9 error stubs (standing/volume pair, lease window/credit pair, protest window/duplicate pair, insufficient use history, docket-phase/window-still-open pair, POD capacity, account posture, violation unresolved, forfeiture not eligible), and 3 cross-cutting-layer stubs (dual_variant, rate_threshold, cascading). Rationale in every case: the §1.8 instance already drives that corner under a strictly tighter boundary/ordering test, so a corner copy would be pure duplication.

**Coverage check:** all 58 §1.6 error ids are now positively asserted somewhere across the two design files (previously-uncovered ids got authored corner instances: the unauthenticated header family, the four-key uniqueness family, self-protest, self-objection, bank-enrollment, the two-sided offset bound, study/right mismatch, injury-analysis-missing, role-denial matrix, claimant ownership scoping, segregation of duties, and the three OCC rules including `ERR_STALE_ACCOUNT_VERSION`).

**Two small coherence edits to SCAFFOLD.yaml** were needed while writing the cascade instances (flagging since it was previously "finished"): the `declare-forfeiture` link-3 side effect now states that a fee reversal driving the balance to exactly 0.00 repairs `DELINQUENT` standing the same way a payment does (needed so the forfeiture cascade's posture recomputation is deterministic), and the `forfeiture_risk_score` formula's last line was renamed `statutory_forfeiture_eligible` → `forfeiture_eligible` to match the field the assessment endpoint actually returns. Also note YAML required quoting the flow-style `grounds` lists that contain `endpoints[...]` / `validations[priority=N]` tokens — those 16 lines are now block lists with quoted items.

**Final lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (65 endpoints, 13 entities, 20 §1.8 instances, 89 §1.9 instances, 1,680 calls scanned).

Orchestrator verification: all three files parse as valid YAML; SCAFFOLD.yaml has no `scaffold_difficulty_design`/`scaffold_corner_design` key; the two design files each carry exactly their single required top-level key. Line counts on disk: SCAFFOLD.yaml 4261, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2221, SCAFFOLD_CORNER_DESIGN.yaml 3895.

## Step 3: Copy shared files — 2026-09-01T02:38:00.000Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-09-01T03:14:00.000Z

PRD complete at `/home/ubuntu/github/CodingPRD/tasks/task_2198_water_rights_transfer_adjudication_support/workspace/PRD.md`.

**Line count:** 459 lines. Ends at §5 with no audit footer.

**Section structure emitted** (domain-derived, not the example PRD's skeleton):
- §1 Introduction — 3 paragraphs (over-appropriation pain point; scope + the two conserved quantities; defensibility, pinned orders, segregation, logical clock).
- §2 Global Specifications, twelve subsections: 2.1 identity/RBAC, 2.2 response envelope (verbatim from the skill's fixed file), 2.3 pagination + every documented sort departure, 2.4 logical clock, 2.5 common properties + the version-less append-only evidence ledger, 2.6 path resolution / nested ownership / 11 404s / 9 body FKs, 2.7 the three OCC rules, 2.8 rounding discipline (2/3/4 dp, whole days), 2.9 both conserved ledger identities, 2.10 cascade discipline + the two pinned derived-status precedence chains, 2.11 validation precedence with three worked consequences, 2.12 segregation of duties.
- §3 Business Logic, ten subsections following the business timeline: 3.1 claimants + right documentation + headgates + use records; 3.2 activation, forfeiture score, declaration cascade, reinstatement; 3.3 consumptive-use quantification + certification; 3.4 draft/submit/resubmit/withdraw; 3.5 injury analysis + protest-window publication; 3.6 protest adjudication + revision cycle + clearance cascade; 3.7 the three dispositions; 3.8 approval conditions' two independent axes + tiered fee; 3.9 banking, deposits, leases, both interval geometries, settlement; 3.10 dockets, claims, objections, decrees.
- §4 Endpoint Definitions — status-code paragraph + strict 4-column table, **65 rows** (all 65 endpoints).
- §5 Error Code Catalogue — strict 2-column table, **58 rows** (all 58 codes).

**Scattering approach:** contract-level material (envelope, pagination, identity, OCC, rounding, the ledger identities, precedence chains, validation ladder) is stated once and precisely in §2; every calculation, state machine and cascade is then dissolved into §3 narrative at the point in the process where it fires, with cross-references by section number rather than restatement. Related rules are deliberately split across subsections (e.g. the fee tier table lives in §3.8 but is invoked from §3.6's hearing branch and §3.7's conditional approval; the settlement calculation lives in §3.9 but is invoked from §3.2's forfeiture cascade; the derived-status precedence lives in §2.10 and is re-derived-by-reference everywhere). Sibling branches are held at equal density (negotiation vs hearing vs dismissal; the three dispositions; the two interval geometries; the two valuation methods).

**Hard Contract results:**
1. **Field-Name Coverage — PASS.** Programmatic diff run twice: 138 entity/input/OCC field names → 0 missing; second pass over enum values, all 12 state machines' states, 58 error ids, 5 role names, 13 entity names and all 65 paths → 0 missing.
2. **Rule Coverage — PASS.** All 12 calculations with every constant present (checked programmatically across formatting variants); all 49 validations present with correct HTTP status and correct relative ordering; all 12 state machines' transitions covered (arrow-literal scan flagged 31 pairs, each manually confirmed covered by prose enumeration such as "reachable from `RESERVED`, `ACTIVE` or `SUSPENDED`" or by the derived-status precedence); all 3 OCC rules; all cascades to depth 4.
3. **§3 Path Purity — PASS.** Scan of the whole §3 span (68k chars): 0 backticked tokens starting with `/`, 0 backticked method+path pairs, 0 bare `GET/POST/PUT/PATCH/DELETE` words, 0 plain-text slash paths. Paths appear only in §2.7 and §4.

Also verified: no pseudocode operators (`==`, `>=`, `+=`, `min(`, `round(`, `IN {`, …) anywhere outside the §2.2 JSON block, and no fuzzy/approximating hedges.

**Coverage of §1.1–§1.7:** all covered in prose — 13 entities and every field (§1.1), 12 state machines over 10 entities including the parallel and cyclic axes (§1.2), 3 OCC rules (§1.2.1), 12 calculations including all 3 dual-variant pairs (§1.3), 49 validations (§1.4), 65 endpoints (§1.5), 58 error codes (§1.6), 5 roles with structural and per-user segregation (§1.7). **No deliberate omissions.**

Four self-corrections made during verification: the `GET /water-rights`, beneficial-use-record, hcu-study and transfer-application list filters in §4 were corrected to the scaffold's actual query parameters; lease reservation's standing gate was corrected from "not `BARRED`" to the stricter `IN_GOOD_STANDING` (priority 24 splits strict/loose by endpoint); and the claim-filing gate order in §3.10 was corrected to duplicate (14) before phase (19) before deadline (33).

One scaffold-internal inconsistency reconciled deliberately: the study-certification side-effect text says "UNADJUDICATED rights become ACTIVE" while `right_status_derivation` states a never-activated right reads `UNADJUDICATED`. The PRD says the status is "re-derived by the pinned precedence", keeping the derivation chain (already stated in §2.10) authoritative rather than asserting the contradictory clause.

As instructed, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced, and no sibling `task_*/` directory was read.

Orchestrator verification: PRD.md is 459 lines, non-truncated (ends mid-error-catalogue table with a complete final row), §4 endpoint table has exactly 65 method rows, and the document contains 104 `ERR_` mentions across §3/§5.

## Step 5: Generate unit tests — 2026-09-01T05:48:00.000Z

Launched concurrently with Step 6 in a single assistant message (physical isolation: `test_suite/` did not exist when the impl-gen subagent started).

All work is complete. Final state of the suite for task 2198:

## Files

**`test_helpers/`** (infrastructure, from earlier sessions): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/`** — `conftest.py` plus 22 test modules, 213 test methods (216 collected cases after 3 parametrizations):

| file | tests | file | tests |
|---|---|---|---|
| test_01_consumptive_use_quantification | 8 | test_12_protest_tracks_and_condition_dimensions | 7 |
| test_02_transfer_application_volume_ledger | 4 | test_13_lease_delivery_and_adjudication_dockets | 17 |
| test_03_protest_filing_and_revision_cycle | 5 | test_14_injury_analysis_arithmetic | 11 |
| test_04_protest_resolution_tracks | 5 | test_15_forfeiture_scoring_and_hcu_constants | 8 |
| test_05_mitigation_fees_and_condition_cascades | 4 | test_16_decree_waterfall_posture_and_status | 9 |
| test_06_lease_interval_geometry | 10 | test_17_validation_priority_ladder | 6 |
| test_07_lease_credit_ledger_and_settlement | 7 | test_18_evidence_deadlines_and_mitigation_bounds | 9 |
| test_08_forfeiture_window_and_docket_phases | 7 | test_19_error_identity_families | 18 |
| test_09_entity_contracts_and_request_shape | 17 | test_20_role_boundaries_and_ownership | 14 |
| test_10_right_and_study_state_machines | 6 | test_21_endpoint_surface_and_computed_reads | 18 |
| test_11_transfer_application_lifecycle | 7 | test_22_concurrency_cascade_and_consistency | 16 |

## Design-index coverage

- **Queue A (Difficulty, §1.8): 20 live instances, 20 translated, 0 skipped** — every instance carries ≥2 tests (files 01–08 plus the priority-ladder and cross-entity tests).
- **Queue B (Corner, §1.9): 114 instances — 25 are `excluded_because` stubs (not translated, per contract); 89 live, 88 translated, 1 skipped.**
  - Skipped: `Corner/state_machines/sm_initial_states_are_server_chosen_and_status_input_ignored` — its distinguishing aspect asserts a newly opened `WaterBankAccount` reads `posture RESTRICTED`, which PRD §3.9 contradicts outright ("comes into existence with all four credit buckets at 0.00, `suspended_lease_count` at 0 and `posture` `OPEN`"). No placeholder, no weakened variant emitted.
  - Section tallies of live instances, all covered: entities 17, state_machines 24, calculations 12, validations 10, endpoints 6, errors 8, rbac 5, cross_cutting_complexity_layers 5, consistency_model 2.

## Tag audit

Mechanical AST audit over all 22 modules: **213/213 tests carry exactly one `Design:` line, and it is the last line of the docstring.** 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances, 0 tags pointing at stub instances.

## Final audits run

- **PRD-citation pass:** 426 quoted passages extracted from every module/class/method docstring and substring-checked against the whitespace-flattened PRD (ellipsis-separated fragments checked individually) — **0 defects** after fixing 19 found this pass, notably a fabricated §3.4 submit sentence in test_11 (replaced with the real "A successful submission moves the application `DRAFT → SUBMITTED`…" pair), a non-existent §2.9 credit-identity phrasing in test_07, ASCII `->` arrows instead of `→` in test_10, and several sentences truncated with a period where the PRD continues.
- **Scaffold pass:** every path used by `api_client` resolves to a declared SCAFFOLD endpoint (55 declared, 0 undeclared); every dict-key literal in the suite is either a declared entity/response field or a local fixture-bundle key.
- `ast.parse` clean on all files, `pyflakes` clean on `test_suite/` (only re-export noise in `test_helpers/__init__.py`), and `pytest --collect-only` collects 216 cases with no import errors.

Orchestrator verification: `python3 -m pytest test_suite --collect-only -q` from the task directory collects 216 tests with no errors; `test_helpers/` has all 9 declared modules and `test_suite/` has conftest.py + 22 test modules on disk.

## Step 6: Generate implementation — 2026-09-01T05:48:00.000Z

Launched concurrently with Step 5 in a single assistant message.

Implementation complete and verified.

## Files created

Root: `/home/ubuntu/github/CodingPRD/tasks/task_2198_water_rights_transfer_adjudication_support/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | `set -euo pipefail`, `cd $(dirname $0)`, guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0.0` |
| `app.py` | 86 | `create_app()`, 13 blueprints, error handlers, `PORT` default 10000 |
| `clock.py` | 75 | logical clock, boots at `2026-08-01T00:00:00Z` |
| `db.py` | 62 | 13 in-memory dicts + deposit list; nothing seeded |
| `errors.py` | 98 | 61-entry error catalog + `ApiError` |
| `response.py` | 60 | `meta`/`response_type`/`data` envelope, `req_` ids |
| `middleware.py` | 69 | role auth, ownership scoping |
| `validate.py` | 238 | body/query coercion, Decimal parsing, pagination |
| `calc.py` | 353 | pure formulas (HCU, injury, fees, forfeiture, settlement, decreed volume, interval geometry) |
| `derive.py` | 449 | ledger recomputation, derived statuses, rollups, priority re-ranking |
| `cascades.py` | 275 | forfeiture, condition-violation, fee-payment, protest-clearance, lease settlement |
| `serialize.py` | 237 | 13 projectors, field order matching the scaffold |
| `routes/*.py` | 2673 | 13 route modules (below) |
| **Total** | **4786** | |

## Endpoint organization (65 total)

- `clock_routes.py` (1) — `POST /_clock/set_current_utc`
- `claimants.py` (4) — create, list, get, `PATCH .../standing`
- `water_rights.py` (7) — create, list, get, activate, reinstate, declare-forfeiture, suspend
- `beneficial_use.py` (2) — create, list (nested under a right)
- `points_of_diversion.py` (2) — create, list
- `hcu_studies.py` (4) — create, list, get, certify
- `transfer_applications.py` (10) — create, list, get, submit, publish, close-protest-period, request-revision, resubmit, decide, withdraw
- `injury_analyses.py` (3) — create, list, get
- `protests.py` (6) — create, list, get, route, resolve, withdraw
- `approval_conditions.py` (5) — list, get, pay, satisfy, violate
- `water_bank.py` (4) — create account, list, get, deposits
- `leases.py` (7) — create, list, get, activate, resume, complete, cancel
- `adjudication.py` (10) — docket create/get/advance-phase, claim create/list/get/examine/verify/object/decree

`app.url_map` yields exactly 65 rules excluding Flask's `/static/...`; a normalized diff against the 65 paths in `SCAFFOLD.yaml` printed "ENDPOINTS MATCH EXACTLY". Every `ERR_*` id raised is in the catalog and every catalog id is reachable.

## Boot verification (final, fresh process on port 18991)

- `bash start.sh` came up cleanly, bound `0.0.0.0:18991`, no reloader.
- `GET /water-rights` → 200, `{"data":[], "meta":{limit:10, offset:0, total_count:0, has_more:false, api_request_id:"req_…", api_request_timestamp:"2026-08-01T00:00:00.000Z"}, "response_type":"array"}` — confirming an empty store and the clock reset at boot.
- `POST /_clock/set_current_utc` → 200, echoes `2026-09-01T12:00:00.000Z` and the envelope timestamp follows the logical clock.
- Unknown path → 404 `ERR_NOT_FOUND`; wrong method → 405 `ERR_METHOD_NOT_ALLOWED`; malformed / non-object / missing body → 400 `ERR_INVALID_REQUEST`; missing headers → 401 `ERR_UNAUTHENTICATED`.
- Process killed by PID; port released. No leftover listeners.

Four progressively deeper smoke runs previously exercised all 65 endpoints and ~35 distinct error ids, confirming the numeric behaviour (HCU volumes, injury gross/net with stipulated offsets, mitigation fee 5000+350, decreed volumes 225.0 and 40.5, lease pro-rata settlement, POD retirement on approval, docket auto-advance to `DECREE_ENTERED`, account posture transitions). One flagged case (`touching 20-30 +5.0` → `ERR_POD_CAPACITY_EXCEEDED`) was traced to a third overlapping lease in the fixture (5.0 + 1.0 > `max_rate_cfs` 5.0), so the half-open geometry is correct and no change was needed.

## Step 6b: Resume-mode audit (run 2) — 2026-09-01T04:05:00.000Z

Second crash recovery. On-disk audit of `/home/ubuntu/github/CodingPRD/tasks/task_2198_water_rights_transfer_adjudication_support`:

| Artifact | Status |
|---|---|
| `SCAFFOLD.yaml` (216787 B) | VALID — `yaml.safe_load` clean, top keys `scenario/domain_name/api_prefix/complexity_profile/response_envelope/entities`, no difficulty/corner keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (137688 B) | VALID — parses, single top key `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` (422511 B) | VALID — parses, single top key `scaffold_corner_design` |
| `workspace/INSTRUCTION.md` (53 lines) | VALID |
| `workspace/PRD.md` (459 lines, 108083 B) | VALID — non-truncated, terminates on the complete error-catalog table |
| `test_helpers/` (9 modules) | VALID |
| `test_suite/` (conftest + 22 modules) | VALID — `pytest --collect-only -q` collects 216 tests, 0 errors |
| `workspace/implementation/` (65 endpoints, 15 route modules) | VALID |
| `workspace/PRD_FINALIZED.md` | ABSENT — Step 8 not reached |
| `workspace/PRD_COMPLETED.md` | ABSENT — Step 9 not reached |

Steps 1–6 confirmed complete; not regenerated. Step 7 was in progress when the run died: the last completed 8-round sweep (`results.{1..8}.json`, 03:20) reports **191/216 passing in all 8 rounds**, and files under `test_suite/`, `test_helpers/` and `implementation/` carry mtimes up to 03:42 — i.e. a batch of fixes was applied but never re-swept. Resuming the Step 7 loop from a fresh 8-round sweep.

## Step 7: Run tests and iterate — 2026-09-01T04:20:00.000Z

Task 2198 is green. Fresh 8-round parallel sweep: **216/216 passing in all 8 rounds**, 0 failed / 0 errors / 0 skipped.

### Subagent summary (verbatim)

**Iterations run: 1** (the baseline sweep itself came back fully clean — no fix round was needed).

The stale `results.{1..8}.json` at 03:20 reporting 191/216 were indeed obsolete. The prior Step 7 subagent's un-swept fix batch (mtimes 03:26–03:42 across `test_suite/`, `test_helpers/`, and `implementation/`) had in fact closed all 25 remaining failures before it was killed; it just never got to run the confirming sweep. I overwrote those stale files with a fresh sweep (`results.1.json` … `results.8.json`, timestamped 03:50, ~280 s per round under 8-way concurrency).

**Tests deleted: none.** The suite still collects exactly 216 cases, matching the count recorded in `worklog.md` at generation time — so the prior run resolved its failures without deleting any test.

**Fixes applied to `test_helpers/`: none by me.**

**Fixes applied to `implementation/`: none by me.**

### Integrity audit of the inherited (un-swept) fix batch

Since I could not diff the prior run's edits (all files are untracked), I audited for the failure modes the protocol forbids, and all came back clean:

- No half-finished edits: `ast.parse` clean on all 32 test modules and all 24 implementation modules.
- No `pytest.mark.skip` / `xfail` / `skipif` / `pytest.skip` anywhere in `test_suite/` or `test_helpers/`.
- No gutted tests: zero `assert True` / bare-`pass` bodies; assertion density stays high in every module (26–178 assert/validate calls per file), including the files edited latest (`test_18` 54, `test_22` 158, `test_12` 81).
- No downgraded error assertions. The only two `status_code == 4xx` sites (`test_11_transfer_application_lifecycle.py:258`, `test_13_lease_delivery_and_adjudication_dockets.py:486`) are each immediately followed by an exact `validate_error(..., ERR_INVALID_STATE, expected_status=409)`, so no exact-`error_id` check was traded for a status check.
- The single `validate_error_is_one_of` relaxation (`test_18_evidence_deadlines_and_mitigation_bounds.py:144`, zero examiner recommendation → `[ERR_RECOMMENDATION_EXCEEDS_CLAIM, ERR_INVALID_REQUEST]`) is a legitimate coverage correction under the stated exception: PRD §3.10 names `ERR_RECOMMENDATION_EXCEEDS_CLAIM` only for "a recommendation above the claim", leaving the lower end of the two-sided bound's error identity underdetermined. It still pins the HTTP status per PRD §5 and still asserts the full no-op (`filing_status` unchanged, `examiner_recommended_af is None`, `version` unchanged).
- No disabled implementation checks: zero `TODO` / `FIXME` / commented-out `raise` or `if` guards in `implementation/`.
- Storage contract intact: `workspace/implementation/db.py` is 13 in-memory dicts plus one deposit list, nothing seeded; no `sqlite`, file `open(`, `json.dump`, `pickle`, or `/tmp` usage anywhere in the implementation (the only `open`/`half_open` grep hits are the `intervals_overlap_half_open` lease-geometry helper).

I removed the transient `run.*.log` files and stale `__pycache__` trees I created. The eight fresh results files are the current, trustworthy record.

### Orchestrator note — reconstructed Step 7 edit surface

The killed run's narrative diff is unrecoverable (its context was discarded), so the orchestrator reconstructed the Step 7 edit surface from mtimes relative to the Step 5/6 generation boundary (~01:30). Files touched during Step 7 fix rounds:

`implementation/` (7 files): `routes/beneficial_use.py` (03:29), `derive.py` (03:32), `routes/water_rights.py` (03:32), `serialize.py` (03:32), `cascades.py` (03:33), `errors.py` (03:40), `routes/protests.py` (03:40).

`test_helpers/` (1 file): `assertions.py` (03:27).

`test_suite/` (17 files): `test_01`, `test_03`, `test_04`, `test_07`, `test_08`, `test_09`, `test_10`, `test_11`, `test_12`, `test_13`, `test_14`, `test_15`, `test_16`, `test_17`, `test_18`, `test_19`, `test_20`, `test_21`, `test_22`.

Because `implementation/` fix count is non-zero, Step 8 is NOT skipped; this file list is passed as the `<step_7_diff>` focus surface.

## Step 8: Finalize PRD — 2026-09-01T04:40:00.000Z

Not skipped: Step 7's reconstructed edit surface includes 7 `implementation/` files, so the 0-fix skip condition does not hold. The `<step_7_diff>` handed to the subagent was the reconstructed file-level surface plus the one known assertion relaxation, with an explicit instruction to recover per-fix intent by reading each listed file.

### Subagent summary (verbatim)

`workspace/PRD_FINALIZED.md` is written. It is a paragraph-level minimal patch of `workspace/PRD.md`: 15 paragraphs revised in place, no new sections, no reordering.

## (a) Size delta

| | PRD.md | PRD_FINALIZED.md | Δ |
|---|---|---|---|
| lines | 459 | 459 | 0 (0.00%) — the document is one paragraph per line |
| characters | 108,083 | 113,659 | +5,576 (**+5.16%**) |
| changed lines | — | 21, 116, 160, 166, 168, 174, 176, 178, 230, 236, 238, 266, 274, 298, 312 | 15 paragraphs |

## (b) Change list

- **§2.1 Roles & Ownership (L21)** — revise — the "Concretely…" enumeration now covers POD / beneficial-use / study / injury-analysis / condition families, protest and claim *operations* (not just filing/withdrawal), and self-read of a `Claimant`; adds that the check is read/write indifferent and applies to any path naming one specific resource or a listing nested under a named parent, that top-level collection listings are neither ownership-filtered nor refused, and that a `DecreeDocket` is unscoped — `routes/water_rights.py:97-113,219`, `routes/beneficial_use.py:25,68`, `routes/protests.py:147`, `routes/claimants.py:47`, `middleware.py:55-69`
- **§2.9 Conserved Ledgers (L116)** — revise — a negative `transferable_af` is *floored at 0.00*, not "rejected before it is applied"; `available_credit_af` floored identically — `derive.py:168-170`, `derive.py:285-287`
- **§3.1 Beneficial Use (L160)** — insert — `reported_diversion_af` and `irrigated_acres` are stored and echoed exactly as supplied, not narrowed to §2.8's 2-decimal default — `routes/beneficial_use.py:45-53`
- **§3.2 Perfecting (L166)** — insert — perfection reachable only from `UNADJUDICATED`; any other status is `ERR_INVALID_STATE` 409, gated *before* the evidence check — `routes/water_rights.py:123-134`
- **§3.2 Abandonment scoring (L168)** — revise — the stored projection is re-stamped by every operation that recomputes the right's volume ledger; a plain read (single or listing) re-derives ledger+status but leaves the stored score alone, so clock advance alone never moves it — `serialize.py:56-60`, `routes/water_rights.py:95-97`, `derive.py:217-245`
- **§3.2 Declaring forfeiture (L174)** — revise — an already-`FORFEITED` right is `ERR_INVALID_STATE` 409, checked *before* eligibility; every other status (incl. `UNADJUDICATED`, `SUSPENDED`) is forfeitable — `routes/water_rights.py:186-198`
- **§3.2 Forfeiture cascade (L176)** — revise — defines "affected": the holder only if a fee was actually reversed, plus holders of accounts funding cancelled leases; all their accounts re-ledger and bump; with nothing reversed and nothing cancelled no account is touched and the holder is re-derived without a bump — `cascades.py:219-256`, `derive.py` `apply_fee_cascade`
- **§3.2 Reinstatement (L178)** — insert — reachable only from `SUSPENDED`; otherwise `ERR_INVALID_STATE` 409, gated after note validation and before the two conditions — `routes/water_rights.py:150-172`
- **§3.6 Protest filing (L230)** — insert — the application must read `PROTEST_PERIOD` or `UNDER_PROTEST`, else `ERR_INVALID_STATE` 409, gated ahead of standing and ahead of the three gates in L232 — `routes/protests.py:40,63-68`
- **§3.6 Routing (L236)** — revise — the only state gate is the protest's own `FILED`; the parent application's status is *not* re-examined (so a protest held across a revision leg stays routable) — `routes/protests.py:159-163`
- **§3.6 Resolution (L238, two edits)** — revise — a non-blank `resolution_note` is required and recorded for **all three** combinations, and `outcome`+`resolution_note` are validated as body well-formedness before the status and pairing checks; the `HEARING`+`DISMISS` clause no longer implies the note is unique to it — `routes/protests.py:184-198,225`
- **§3.8 Fee dimensions (L266)** — insert — a `NOT_APPLICABLE` condition carries a zeroed (not absent) fee block: 0.00 / 0.000 / 0.00 / 0.00, never re-priced — `cascades.py:268-289`, `serialize.py` `approval_condition`
- **§3.8 Violation cascade (L274)** — insert — when the right is outside `ACTIVE`/`ENCUMBERED`/`PARTIALLY_TRANSFERRED` the violation still stands and links 3–4 still fire, but the right's row is neither re-statused nor bumped — `cascades.py:114,130-135`
- **§3.9 Lease cancellation (L298)** — revise — lease and account always bump; the source right bumps only where used volume actually moved, so cancelling from `RESERVED` leaves the right's row untouched — `derive.py:217-255` (`recompute_right(bump=True)`), `routes/leases.py` `_refresh_after_lease_move`
- **§3.10 Examination (L312)** — revise — the bound's two ends carry different identities: above the claim is `ERR_RECOMMENDATION_EXCEEDS_CLAIM` 422, at-or-below zero is `ERR_INVALID_REQUEST` 400 — `routes/adjudication.py:241`, `routes/adjudication.py:256-261`, `validate.py` `req_decimal` (this is the item flagged at `test_18…:144`)

## (c) Pre-edit search log

For every edit: (a) subject → (b) impl paths enumerated → (c) wording adjustment.

1. **Ownership scope.** (b) Grepped every `require_owner` / `owner_precheck` callsite across all 12 route modules; confirmed all single-resource GETs are checked except `get_docket`; all nested lists checked; all six top-level listings unchecked and unfiltered; unchecked path-writes (`create_pod`, `create_study`, `publish`, `resume`/`complete_lease`, `violate`, `advance_phase`, examine/verify/decree, route/resolve) are staff-only, where `require_owner` is a no-op (`middleware.py:55`); `object_claim` uses the inverse check already carved out; there is no `GET /claimants` listing. (c) Framed the rule as "names one specific resource in its path, or a listing under a named parent", carved out top-level listings and `DecreeDocket` explicitly rather than restating per-endpoint.
2. **Negative floor.** (b) `derive.right_ledger` and `derive.bank_ledger` are the only two computation sites; grepped for any pre-application rejection of a negative bucket — none exists; budget gates in submit/resubmit/deposit/reserve read the already-floored value. (c) Swapped "rejected before it is applied" for "reports 0.00 instead" and left §2.9's identity sentence verbatim (an under-determined corner beats a false mechanism).
3. **Beneficial-use precision.** (b) `routes/beneficial_use.py:52-53` (raw store), `serialize.beneficial_use_record`, and all three downstream consumers (`calc.admissible_use_records`, `calc.hcu_transferable_volume` q3, `calc.forfeiture_assessment` mean q3); confirmed `place_of_use_acres`/`authorized_diversion_af` *are* quantized so the exemption is specific to these two fields. (c) Scoped the clause to exactly the two fields and cross-referenced §2.8/§3.3 so it reads as a stated exception, not a new default.
4. **Perfection state gate.** (b) `activate_right` is the only activation path; checked that `_activated` is also set by `reinstate_right:175`, that `recompute_right` runs before the gate so the status is fresh, and that POD promotion is unchanged. (c) Named the error and pinned only the ordering relative to the evidence check.
5. **Stored score refresh.** (b) `refresh_forfeiture` callers: `recompute_right(refresh_score=True)` and `cascades.condition_violation:133`; `refresh_score=False` appears in exactly two places — `serialize.py:58` and `routes/water_rights.py:97`; ~15 mutation sites default to `True`, so the PRD's four-event list was narrower than impl. (c) Widened to "every operation that recomputes the right's volume ledger" and kept the original four-event list as an inclusive example, then pinned the read-side exception.
6. **Declare-forfeiture gates.** (b) `declare_forfeiture:186-198` (note → sticky-state → eligibility), plus `derive.right_ledger`'s all-zero FORFEITED branch and `derive_right_status`'s sticky first rule. (c) Named both errors, pinned their order, and enumerated the forfeitable statuses literally rather than by category.
7. **Forfeiture cascade account set.** (b) `cascades.forfeiture:205-256` link by link, `release_conditions` return value, `derive.apply_fee_cascade` (unconditional `db.touch(claimant)` + touch of every account of that claimant), `derive.accounts_for_claimant`, and the `recompute_claimant`-without-bump tail at :250. (c) Replaced the bare word "affected" with the exact party set and added the no-op case.
8. **Reinstatement state gate.** (b) `reinstate_right:150-177`: note validation, `SUSPENDED` gate, VIOLATED-condition scan, then the ≥5-year check — both later failures share `ERR_VIOLATION_UNRESOLVED`, which the PRD already states. (c) Inserted only the missing gate and its position; left the two conditions verbatim.
9. **Protest filing app-status gate.** (b) `create_protest:40,63-96` full gate order; cross-checked the writers of `protest_deadline` (`publish_app` sets it, `request_revision` clears it) to confirm the `deadline is None` branch is unreachable behind the new gate. (c) Placed the gate in §3.6's standing paragraph, stated its precedence over standing and over L232's three gates, and named `REVISION_REQUESTED` as the reachable case — without disturbing L232's own ordering claim.
10. **Routing gate.** (b) `route_protest:151-168` — the sole state check is on the protest; confirmed `request_revision` does not resolve outstanding protests, making a `FILED` protest under a `REVISION_REQUESTED` application reachable. (c) Removed the false parent-status requirement and said outright that the parent's status is not re-examined.
11. **`resolution_note`.** (b) `resolve_protest:183-234`: `outcome`+`resolution_note` validated for all combinations before the status gate; `:225` records the note on every outcome; `serialize.protest` exposes it; `create_protest:108` initialises it to null. Confirmed `stipulated_offset_af` is validated *after* the status and pairing gates, so the ordering claim is limited to the two universal fields. (c) Made the note universal, pinned only the ordering that impl actually exhibits, and reduced the `HEARING`+`DISMISS` sentence to a back-reference.
12. **Zeroed fee block.** (b) `cascades.create_condition:268-289` is the only condition constructor (both callers: `decide_app:532` and `resolve_protest:240`); `serialize.approval_condition` emits all four fields; grepped `pay`/`satisfy`/`violate`/`release_conditions` — none rewrites a fee field. (c) Attached the zeroed block to the `NOT_APPLICABLE` case and added "never revised" only after confirming no re-pricing path exists. Deliberately left L266's `required_af > 0` clause and L264's "zero or more" alone: the clause is unreachable because `transfer_applications.py:424` already requires `gt=0` upstream, and that file is outside the Step 7 surface.
13. **Violation on a non-suspendable right.** (b) `cascades.condition_violation:114-152`; `approval_conditions.violate_condition:112` has no right-status gate; confirmed links 3 and 4 sit outside the `if`, and that `recompute_right` at :130 refreshes the score without touching the row. (c) Said "neither re-statused nor bumped" and stayed silent on the score, since the score *is* re-stamped without a version move.
14. **Cancellation bump.** (b) `derive.recompute_right`'s before/after tuple (four buckets + status), its two `bump=True` callers (`_refresh_after_lease_move`, `withdraw_app`), and each lease transition's effect on the right's ledger: activate/resume move nothing (PRD claims no bump there), complete and cancel-with-`used_af`>0 do, cancel-from-`RESERVED` does not. (c) Conditioned only the right's bump on the movement the PRD already describes one sentence earlier; left the lease and account claims absolute.
15. **Examine lower bound.** (b) `routes/adjudication.py:241` (`req_decimal(..., gt=0)` → `validate.invalid()` → `ERR_INVALID_REQUEST` 400) and `:256-261`; grepped `ERR_RECOMMENDATION_EXCEEDS_CLAIM` — raised nowhere else; contrasted against `routes/protests.py:209-222`, where impl deliberately gives *both* ends of the offset bound `ERR_OFFSET_EXCEEDS_CLAIM`. (c) Split the two identities and named the §3.6 contrast explicitly so the parallel bound is not accidentally re-read; left §3.6's offset wording untouched. Did not pin examine's state-vs-docket-phase ordering, since `adjudication.py` is not on the Step 7 fix surface.

Orchestrator verification: `workspace/PRD_FINALIZED.md` on disk, 459 lines / 113,659 chars, terminating on the complete error-catalog table.

## Step 9: Complete PRD — 2026-09-01T05:05:00.000Z

Always runs. Source document: `workspace/PRD_FINALIZED.md` (Step 8 output).

### Subagent summary (verbatim)

All 55 planned edits are applied and `PRD_COMPLETED.md` is on disk.

## (a) File metrics

| | lines | chars |
|---|---|---|
| `workspace/PRD_FINALIZED.md` (source) | 459 | 113,659 |
| `workspace/PRD_COMPLETED.md` | 459 | 126,189 |

Char-delta **+12,530** on disk (+12,444 excluding the trailing-newline accounting); line count unchanged (all edits are in-paragraph; no sections, paragraphs, or table rows added or removed). 54 of 459 lines differ.

## (b) Counts

- **ambiguity-pins: 43**
- **mismatch-revisions: 12**
- total changes: 55

## (c) Change log

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the §2.4 logical clock, not wall-clock — `implementation/response.py:35`
- §2.2 — insert — ambiguity — `total_count` counts filter matches before windowing; `has_more` is `offset + len(data) < total_count` — `implementation/response.py:49`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, and a filter query param outside its enum, are `ERR_INVALID_REQUEST`; an empty-string query param is treated as absent — `implementation/validate.py:189`
- §2.3 — revise — **mismatch** — tie-break is the server's internal creation sequence, descending on `created_at DESC` listings and ascending on default-ascending listings, not `id ASC` — `implementation/routes/common.py:103`
- §2.3 — insert — ambiguity — the three business orderings compare the leading key as a stored string, then fall back to `created_at` asc then creation sequence asc — `implementation/routes/common.py:111`
- §2.4 — insert — ambiguity — clock setter echoes a single `current_utc` field normalised to 3 fractional digits + `Z`; unparseable input is `ERR_INVALID_REQUEST` — `implementation/clock.py:20`
- §2.5 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, so rows created without clock movement share an identical `created_at` — `implementation/db.py:40`
- §2.7 — insert — ambiguity — each `expected_*_version` is a non-negative integer; missing or non-integer fails as `ERR_INVALID_REQUEST`, not as a 412 — `implementation/validate.py:120`
- §2.8 — insert — ambiguity — which figures are 3-decimal (`authorized_rate_cfs`, `max_rate_cfs`, `diversion_rate_cfs`) versus 2-decimal (`place_of_use_acres`, `stream_miles_from_headwater`, `pod_move_miles`, `rental_rate_usd_per_af`) — `implementation/routes/water_rights.py:64`
- §2.11 — insert — ambiguity — JSON `null` equals omission; absent/empty/`null` body reads as `{}`; all free-text notes 1–500 chars except `objection_basis`/`objection_note` at 240, with only `decision_note` and `resolution_note` echoed; the three body-scoped ownership prechecks fire only on a raw string that already resolves — `implementation/validate.py:34`, `implementation/routes/common.py:131`, `implementation/serialize.py:126`
- §3.1 — insert — ambiguity — `contact_email` is 1–254 chars — `implementation/routes/claimants.py:25`
- §3.1 — insert — ambiguity — re-deriving the two claimant counters is not a mutation and does not bump `updated_at`/`version` — `implementation/derive.py:350`
- §3.1 — insert — ambiguity — a standing change bumps every one of the holder's accounts unconditionally, whether or not posture moves — `implementation/derive.py:375`
- §3.2 — insert — ambiguity — `nonuse_component`, `suspended_penalty` and `meter_credit` are emitted as whole numbers — `implementation/routes/water_rights.py:235`
- §3.3 — insert — ambiguity — study years are bounded 1850–2100 — `implementation/routes/hcu_studies.py:34`
- §3.3 — revise — **mismatch** — certification gate order is stale version → study `DRAFT` → right status, and `qualifying_year_count` is structurally guaranteed rather than separately checked — `implementation/routes/hcu_studies.py:112`
- §3.4 — insert — ambiguity — `null` counts as absent for scope coherence, and body-FK existence outranks it so an unresolvable `proposed_point_of_diversion_id` is a 404 — `implementation/routes/transfer_applications.py:60`
- §3.4 — insert — ambiguity — resubmission gate order: stale version → states → right status → standing → revision cap → swapped budget — `implementation/routes/transfer_applications.py:352`
- §3.4 — insert — ambiguity — withdrawal from `DRAFT` leaves the right's row entirely untouched (no `updated_at`, no `version`) — `implementation/routes/transfer_applications.py:589`
- §3.5 — insert — ambiguity — an injury analysis may only be prepared against one of the six non-terminal application statuses — `implementation/routes/injury_analyses.py:43`
- §3.5 — insert — ambiguity — the `SUBMITTED` gate precedes the analysis-existence check, and `protest_deadline` is thirty/fifteen whole days from the clock, never from the analysis — `implementation/routes/transfer_applications.py:270`
- §3.5 — revise — **mismatch** — close-protest-period checks state before deadline and never separately enforces the unresolved count; it always lands on `READY_FOR_DECISION` — `implementation/routes/transfer_applications.py:285`
- §3.6 — insert — ambiguity — protestant-identity mismatch is `ERR_NOT_RESOURCE_OWNER` judged on the raw payload ahead of well-formedness — `implementation/routes/protests.py:48`
- §3.6 — insert — ambiguity — filing gate order is temporal → self-protest → duplicate — `implementation/routes/protests.py:78`
- §3.6 — insert — ambiguity — missing `stipulated_offset_af`/`condition_type` on the stipulation branches is `ERR_INVALID_REQUEST`, read after status and pairing — `implementation/routes/protests.py:203`
- §3.6 — insert — ambiguity — every resolution/withdrawal bumps the application's `version` whether or not the clearance cascade fires; the right's moves only when it does — `implementation/routes/protests.py:171`
- §3.6 — insert — ambiguity — the "at least one unresolved protest" requirement is guaranteed by the `UNDER_PROTEST` gate and never separately tested — `implementation/routes/transfer_applications.py:325`
- §3.7 — insert — ambiguity — `conditions` entry shape: mandatory `required_af > 0`, enumerated `condition_type`, all parsed as well-formedness before status — `implementation/routes/transfer_applications.py:423`
- §3.7 — revise — **mismatch** — disposition pre-check order is state → segregation (study before protests) → `FINALIZED` analysis (most recent wins), and the `requested_af ≤ encumbered_af` identity is structural, carrying no error — `implementation/routes/transfer_applications.py:476`
- §3.7 — insert — ambiguity — conditional approval bumps the holder and all its accounts even when no fee was assessed — `implementation/derive.py:356`
- §3.8 — revise — **mismatch** — `required_af` is always strictly greater than zero (both creating paths supply a positive figure); it is not "zero or more, defaulting to 0" — `implementation/routes/transfer_applications.py:424`
- §3.8 — revise — **mismatch** — `MITIGATION_PAYMENT` is the only discriminator actually applied for `OUTSTANDING`; the `required_af > 0` conjunct is vacuous — `implementation/cascades.py:60`
- §3.8 — insert — ambiguity — payment takes no body, requires `payment_status == OUTSTANDING` (`ERR_INVALID_STATE`), and that gate precedes the standing gate — `implementation/routes/approval_conditions.py:60`
- §3.8 — insert — ambiguity — compliance sign-off reads the compliance axis first, so `SATISFIED`/`RELEASED` reports `ERR_INVALID_STATE` regardless of fees — `implementation/routes/approval_conditions.py:95`
- §3.8 — insert — ambiguity — violation requires `IMPOSED`; anything else is `ERR_INVALID_STATE` and no cascade fires — `implementation/routes/approval_conditions.py:119`
- §3.9 — insert — ambiguity — `deposit_af` is strictly greater than zero at 2 decimal places — `implementation/routes/water_bank.py:87`
- §3.9 — insert — ambiguity — the funding account's holder must equal the right's holder, reported as `ERR_POD_RIGHT_MISMATCH` right after the headgate test — `implementation/routes/leases.py:61`
- §3.9 — insert — ambiguity — activation bumps lease and account only, leaves the right untouched, and orders `RESERVED` → posture → headgate → timing — `implementation/routes/leases.py:215`
- §3.9 — insert — ambiguity — resumption bumps lease and account only, orders `SUSPENDED` → right status → timing, and is not ownership-scoped — `implementation/routes/leases.py:258`
- §3.9 — insert — ambiguity — completion requires `ACTIVE` (`ERR_INVALID_STATE`) before the timing gate — `implementation/routes/leases.py:294`
- §3.9 — insert — ambiguity — cancellation's reachability gate precedes the timing gate, which is `ERR_LEASE_WINDOW_TIMING` — `implementation/routes/leases.py:326`
- §3.10 — insert — ambiguity — `docket_number` is 1–40 chars — `implementation/routes/adjudication.py:47`
- §3.10 — insert — ambiguity — a `target_phase` outside the four values is `ERR_INVALID_REQUEST`; the successor check precedes every temporal and child gate — `implementation/routes/adjudication.py:88`
- §3.10 — insert — ambiguity — examination requires the claim to read `FILED`, checked before the docket phase, with the recommendation bound last — `implementation/routes/adjudication.py:244`
- §3.10 — revise — **mismatch** — the verification axis accepts only `UNVERIFIED→FIELD_VERIFIED`, `UNVERIFIED→DISPUTED` and `DISPUTED→FIELD_VERIFIED`; other movements are `ERR_INVALID_STATE`, judged before the evidence requirement — `implementation/routes/adjudication.py:278`
- §3.10 — insert — ambiguity — objecting requires the claim to read `EXAMINED`/`OBJECTED`, checked before docket phase, which precedes the self-objection test — `implementation/routes/adjudication.py:317`
- §3.10 — insert — ambiguity — decree gate order is claim `filing_status` → docket phase → verification guard — `implementation/routes/adjudication.py:349`
- §3.10 — revise — **mismatch** — re-ranking bumps only claims whose rank actually changed — `implementation/routes/adjudication.py:380`
- §4 `GET /water-rights` — revise — **mismatch** — ordering tie-break is creation sequence descending, not `id ASC` — `implementation/routes/common.py:106`
- §4 `GET /transfer-applications` — revise — **mismatch** — same ordering correction — `implementation/routes/common.py:106`
- §4 `GET /transfer-applications/{id}` — revise — **mismatch** — the field is `revision_round`, not a "revision count" — `implementation/serialize.py:104`
- §4 `POST …/publish` — revise — **mismatch** — `protest_deadline` comes from the logical clock (30 days, or 15 after a revision), not from the finalized analysis — `implementation/routes/transfer_applications.py:270`
- §4 `POST …/close-protest-period` — revise — **mismatch** — always `PROTEST_PERIOD → READY_FOR_DECISION`; it never routes to `UNDER_PROTEST` — `implementation/routes/transfer_applications.py:285`
- §4 `POST …/request-revision` — revise — **mismatch** — it clears `protest_deadline`; `revision_round` is incremented on resubmission instead — `implementation/routes/transfer_applications.py:334`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) complete the envelope-level surface — `implementation/errors.py:66`, `implementation/app.py:56`

Judgment calls worth flagging: PRD-stated gates that the implementation never reaches (certify's `qualifying_year_count >= 1`, close-protest-period's unresolved count, request-revision's unresolved-protest requirement, decide's `requested_af ≤ encumbered_af`, §3.8's positive-`required_af` conjunct) were reworded as structurally guaranteed rather than deleted, since impl exhibits no contrary behavior. `ERR_BENEFICIAL_USE_RECORD_NOT_FOUND` was left as-is (unreachable — no endpoint addresses a BUR by id), and the three envelope-level errors went into §5's intro prose rather than as new table rows, to honor the "never add new sections" constraint.

---

# PIPELINE COMPLETE — 2026-09-01T05:05:00.000Z

All nine steps finished. Final artifact inventory for `task_2198_water_rights_transfer_adjudication_support`:

| Artifact | Size | Status |
|---|---|---|
| `SCAFFOLD.yaml` | 216,787 B | Step 2 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 137,688 B | Step 2 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 422,511 B | Step 2 |
| `workspace/INSTRUCTION.md` | 53 lines | Step 3 |
| `workspace/PRD.md` | 459 lines / 108,083 B | Step 4 |
| `test_helpers/` | 9 modules | Step 5 |
| `test_suite/` | conftest + 22 modules, 216 tests | Step 5 |
| `workspace/implementation/` | 24 modules, 65 endpoints, ~4,800 lines | Step 6 |
| `workspace/implementation/results.{1..8}.json` | 8 files | Step 7 — **216/216 in every round** |
| `workspace/PRD_FINALIZED.md` | 459 lines / 113,659 B | Step 8 — 15 paragraph revisions |
| `workspace/PRD_COMPLETED.md` | 459 lines / 126,189 B | Step 9 — 43 ambiguity-pins + 12 mismatch-revisions |

Test status: **216 passed / 216 total in all 8 parallel rounds**, 0 failed, 0 errors, 0 skipped, 0 tests deleted across the whole pipeline.
