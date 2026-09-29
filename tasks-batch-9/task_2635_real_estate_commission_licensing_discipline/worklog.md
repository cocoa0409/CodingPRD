# Worklog — task_2635_real_estate_commission_licensing_discipline

## Step 1: Create task directory — 2026-09-03T23:02:18.774Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2635_real_estate_commission_licensing_discipline` and its `workspace/` subdirectory. Index 2635 was fixed by the scenario number (no ./tasks/ scan, no auto-allocation) because up to 32 pipelines run concurrently on this host.

## Step 2: Scaffold generation — 2026-09-04T00:55:00Z

Generated the three scaffold artifacts from the scenario text and the scaffold-generator skill spec alone (no sibling task inspected):

- `SCAFFOLD.yaml` (3080 lines) — §1.0-§1.7: 15 entities, 13 state machines, 3 concurrency rules, 7 calculations, 51 validations, 60 endpoints, 61 errors, 10 roles. Profile: compliance_audit / multi_party_negotiation, graph topology, cyclic shape, segregation_of_duties, immediate consistency, expert_plus.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2199 lines) — 9 difficulty rules x 21 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (4226 lines) — 9 guide sections x 90 instances (50 with full test recipes, 40 `excluded_because` stubs).

`scaffold_lint.py`: VERDICT clean lint (1127 calls scanned). All 61 error ids are triggered somewhere across §1.8/§1.9; placeholder closure verified programmatically; instance names unique across both design files; every stub citation resolves to a real §1.8 instance.

Twelve §1.5/§1.2/§1.4 audit findings were fixed in SCAFFOLD.yaml while writing §1.8/§1.9 (see the final report).

### Step 2 — verbatim subagent summary

Done. All three scaffold artifacts are complete, parse cleanly, and pass the lint.

## Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2635_real_estate_commission_licensing_discipline/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | 3080 | §1.0–§1.7 + preamble (scenario verbatim, verified byte-identical). No `scaffold_difficulty_design` / `scaffold_corner_design` keys. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2199 | single key `scaffold_difficulty_design`: 9 rules × 21 instances |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4226 | single key `scaffold_corner_design`: 9 sections × 90 instances (50 full test recipes, 40 `excluded_because` stubs) |

## Inventory (§1.0–§1.7)

15 entities, 13 state machines (Licensee carries two parallel dimensions: `license_status` × `discipline_status`), 3 concurrency rules, 7 calculations, 51 validations, 60 endpoints, 61 errors, 10 roles. `api_prefix: /commission`; profile `compliance_audit` / `multi_party_negotiation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, difficulty `expert_plus`. Logical clock defaults to `2026-08-01T00:00:00Z`; `created_at ASC` is the only sanctioned ordering.

Domain spine: licensing (education/exam/affiliation/transfer/inactive+reactivation with CE), brokerage supervision (trust accounts, ledger, record retention, supervision posture), complaints (misrepresentation / agency disclosure / commission dispute / trust shortage), trust audits (BOOK vs BANK shortage, remediation orders, escalation), consent agreements and hearings with sanction orders, recovery fund waterfall with claim window/caps/assessment/clawback, advertising + team names, and education provider/instructor approval.

## §1.8 — 9 difficulty rules × 21 instances
`dual_variant_calc` (2), `combinatorial_formula` (2), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (3), `boundary_precision_check` (2), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (3), `compensating_invariant` (2).

## §1.9 — breadth walk over the claim-extraction guide
entities 12 (11 real), state_machines 14 (9), calculations 7 (2), validations 20 (17), endpoints 7 (2), errors 16 (stubs, triggerability sweep), rbac 7 (5), cross_cutting_complexity_layers 6 (3 real = one OCC instance per §1.2.1 rule), consistency_model 1 (real).

## Coverage audit
- **Lint verdict** (verbatim):
```
Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     15
  §1.8 instances scanned:     21
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1127

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
- **Errors**: 61/61 declared error ids are triggered somewhere across §1.8/§1.9 (programmatic scan, zero unmentioned).
- **Placeholder closure**: 0 unbound `${var}` across all 1127 calls and all assert strings (checked with a script over both design files).
- **Names**: unique across both design files; every stub's `difficulty_instance` resolves to a real §1.8 instance, and all 40 citations were normalised to the actual `rule_id / instance_name` form. No stub carries a `test_recipe`; no real instance is missing `distinguishing_aspect` or `test_recipe`.

## Twelve §1.5/§1.2/§1.4 audit findings fixed in SCAFFOLD.yaml during §1.8/§1.9 generation
1–7 (earlier passes): vacatur COMPENSATION-5 text; priority 9/35 exam-attempt carve-out; provider term unified on `approval_years × 365`; Brokerage `PENDING→ACTIVE` defers broker issuance to the affiliation call; validation 12 narrowed to vacatur + fine payments with the claim-filing exemption; `Brokerage to: CLOSED` re-anchored to `from: SUSPENDED` with a normative ordering note.
8. Priority 37 / `ERR_CE_HOURS_INSUFFICIENT` extended to the affiliation-transfer branch — the ACTIVE→ACTIVE `ce_deficient == false` precondition previously had no declared error.
9. `ERR_CONSENT_ALREADY_OPEN` was unreachable (priority 9 always answered first) → priority 9 carve-out for `CONSENT_PENDING` / `HEARING_SCHEDULED` plus a reciprocal note on priority 39.
10. Three §1.8 audit chains would have died on `ERR_FIELDWORK_NOT_STARTED` → `fieldwork_start_at` moved to the default clock instant.
11. RESTRICTED-account ambiguity resolved in three places: DISBURSEMENT is the only barred entry type.
12. **New this session** — ProviderAdmin ownership in validation 6 was unresolvable (no field bound an admin to a provider): added `EducationProvider.admin_user_id` (input, `default: null`), added `admin_user_id?` to `POST /commission/education-providers`, and made priority 6 explicit that a ProviderAdmin write against a provider with a null `admin_user_id` is always refused. Kept optional so no existing §1.8/§1.9 call breaks required-field lint.

Orchestrator verification: all three files parse as YAML; SCAFFOLD.yaml has neither design key; the two design files each have exactly one top-level key.

## Step 3: Copy shared files — 2026-09-04T00:58:00Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: PRD generation — 2026-09-04T01:18:00Z

Orchestrator verification before proceeding: `PRD.md` is 586 lines / 122,400 bytes; headings run §1 Introduction → §2.1–§2.11 → §3.1–§3.13 → §4 API Endpoint Definitions → §5 Error Code Catalogue; the file ends on a complete §5 table row (`| \`ERR_REINSTATEMENT_FEE_MISMATCH\` | 422 |`), i.e. a real section boundary, so the known doc-generator truncation failure did not occur. Forbidden-phrase scan for the difficulty directive ("expert level" / "expert_plus" / "test_recipe") returns 0 hits — the Step 2-only difficulty instruction did not leak into the PRD.

### Verbatim subagent summary

PRD generation is complete and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — **586 lines / 122,400 bytes**, written in 8 incremental `cat >>` appends (no single giant Write), plus 3 small `Edit` fixes.

**Section inventory (lines of body per heading)**

| Section | Lines |
|---|---|
| Title | 1 |
| §1 Introduction | 7 |
| §2 preamble | 3 |
| §2.1 Actors, Headers and RBAC | 27 |
| §2.2 API Response Structure (verbatim) | 48 |
| §2.3 Pagination and List Ordering | 7 |
| §2.4 Common Record Properties | 9 |
| §2.5 The Logical Commission Clock | 5 |
| §2.6 Reference Resolution and Nested Paths | 5 |
| §2.7 Stale-View Protection on Contended Parents | 9 |
| §2.8 Cascade Discipline and Same-Request Settlement | 9 |
| §2.9 Integers, Hours and Rounding | 7 |
| §2.10 Segregation of Duties | 9 |
| §2.11 Order of Rule Evaluation (all 51 rungs) | 57 |
| §3.1–§3.13 Business Logic & Workflows | 221 |
| §4 API Endpoint Definitions | 66 (60 rows) |
| §5 Error Code Catalogue | 66 (61 rows) |

§3 subsections: 3.1 Licence Applications and the Examination Gate; 3.2 Brokerage Registration, Trust Accounts and Supervision Posture; 3.3 Affiliation, Issuance and Licence Transfer; 3.4 Parking a Licence, CE and the Cost of Coming Back; 3.5 Education Provider and Instructor Oversight; 3.6 Trust Ledger Stewardship; 3.7 Audit Reconciliation, Remediation and Escalation; 3.8 Complaint Intake, Screening and Case Prioritisation; 3.9 Two Roads From Probable Cause; 3.10 Sanction Orders, Fine Collection and Vacatur; 3.11 The Recovery Fund: Claims, Caps and the Award Waterfall; 3.12 Advertising, Team and Branch Name Governance; 3.13 The Compliance Sweep.

**Verification**
- Tail check: document ends at a real boundary — the final §5 table row `| \`ERR_REINSTATEMENT_FEE_MISMATCH\` | 422 |`. No mid-sentence truncation; no content after §5.
- §2.2 byte-diffed against `section-2.2-response-structure.md`: identical (only a trailing blank separator line differs).
- §4 has exactly 60 rows for the scaffold's 60 endpoints; §5 has exactly 61 rows for the 61 unique errors; all 61 error IDs are also referenced in §2/§3 prose (zero orphan codes).
- **Contract 1 (Field-Name Coverage): PASS** — 170 mechanically extracted required tokens (132 entity fields, 93 write inputs, 33 query params, 1 path param, deduped), every one present as a standalone backticked span. Two passes run; the only miss found (`decision`) was fixed.
- **Contract 2 (Rule Coverage): PASS** — all 51 validation priorities with error IDs, HTTP statuses and `applies_to` scopes in §2.11; all 3 OCC rules in §2.7; every state-machine `from`/`to` state across all 12 machines present (checked mechanically); every enum member of every entity field present (checked mechanically); all 7 calculations reproduced with their constants; sibling branches given symmetric treatment (BOOK/BANK bases, both hearing findings, both score variants, all 5 complaint dispositions, all 3 review decisions, all 5 vacatur compensations, all 5 sweep steps).
- **Contract 3 (§3 Path Purity): PASS** — no backticked token in §3 begins with `/`, contains `/`, or names an HTTP method.
- Forbidden-phrase scan: "harder than expert level", "expert level", "expert_plus", "difficulty", "test_recipe" — **0 hits**. Fuzzy-word scan ("approximately", "roughly", "etc.", "and so on", "as needed", "reasonable") — **0 hits** after rewriting one §2.6 sentence into an explicit per-family 404 mapping.
- Withheld files were never opened: no read of `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory.

**Zero-Silence-Rule judgement calls** (scaffold self-conflicts resolved by majority of authoritative sources; each resolved to a single determinate reading):
1. `screener_user_id` — the endpoint's `side_effects` say it is stamped at intake, but the field description ("default null", set by the counsel who *first dispositioned out of SUBMITTED") and the state machine both say otherwise. Documented as **null at intake, stamped on the first disposition**.
2. `amendment_count` — endpoint `side_effects` say incremented on `REQUEST_AMENDMENT`; the field description ("accepted complainant amendments") and the `AMENDMENT_REQUESTED → INVESTIGATION` side effect say incremented on the amendment itself. Documented as **incremented when the complainant supplies the amendment**.
3. `investigator_user_id` is both an optional payload field and a state-machine side effect equal to `X-User-ID`. Documented as **recorded from the acting counsel's `X-User-ID`**, with the payload field named for coverage.
4. The `SUBMITTED → INVESTIGATION` precondition "respondent `license_status` != `DENIED`" nominates no error code. Assigned **`ERR_INVALID_STATE`** (the priority-9 state rung).
5. A hearing finding of `NO_VIOLATION` must clear the respondent, but no `PENDING_HEARING → CLEARED` transition is declared. Documented as **`PENDING_HEARING → CLEARED`, subject to the same "no other open complaint remains" condition** as the declared clearing transition.
6. A `DECIDE` that omits the required `finding`/`sanction_type` has no dedicated code (`ERR_MISSING_FIELD` does not exist in the catalogue). Assigned **`ERR_INVALID_REQUEST`**.
7. Earlier calls carried forward: brokerage-name uniqueness is asserted without an error code (documented without inventing one), `ProviderAdmin` ownership semantics, the scope of the prelicense-hours check, and the `remediation_days` default were all resolved in favour of the authoritative field/validation table.
8. §3 runs to 13 subsections, above the skill's soft 5–9 guidance. Chosen deliberately: collapsing further would have buried either the waterfall re-pass or the sweep's step ordering inside an unrelated narrative.

## Step 5: Unit test generation — 2026-09-04T02:55:00Z

Orchestrator note on execution order (deviation, recorded for honesty): Steps 5 and 6 were intended to launch concurrently in one assistant message so that the implementation generator would be *physically* unable to see `test_suite/`, which would not yet exist. Only the Step 5 agent went out in that message, so Step 6 ran afterwards, with `test_suite/` and `test_helpers/` already on disk. Mitigation applied: the Step 6 prompt carried an absolute, explicitly enumerated prohibition on reading, listing, globbing or grepping `test_suite/`, `test_helpers/`, either design YAML, and any sibling task — and its returned summary describes only PRD/SCAFFOLD-derived behaviour plus self-constructed curl smoke calls, with no reference to any test file. Treated as acceptable; no regeneration.

Orchestrator verification: `test_helpers/` and `test_suite/` are at the task root; `workspace/test_helpers` and `workspace/test_suite` do not exist; 217 `def test_` functions counted across `test_suite/`.

### Verbatim subagent summary

Final file is in place and every verification pass is green.

## File inventory

`test_helpers/` — 2,555 lines
```
  48 __init__.py      300 api_client.py    150 api_errors.py   283 assertions.py
  59 clock.py         195 constants.py     383 factories.py    775 fixtures.py
 109 test_users.py    253 types.py
```

`test_suite/` — 8,931 lines, 217 tests
```
  22 conftest.py
 281 test_01_dual_variant_calculations.py      254 test_02_combinatorial_formulas.py
 300 test_03_non_linear_state_machines.py      355 test_04_transitive_cascades.py
 412 test_05_priority_conflicts.py             254 test_06_boundary_precision.py
 339 test_07_cross_entity_state.py             347 test_08_resource_temporal_overlap.py
 379 test_09_compensating_invariants.py        815 test_10_entity_contracts.py
 933 test_11_state_machine_edges.py            256 test_12_calculation_details.py
 687 test_13_validation_gates.py               886 test_14_validation_cascades.py
 775 test_15_validation_caps.py                294 test_16_endpoint_behaviours.py
 760 test_17_role_boundaries.py                446 test_18_optimistic_concurrency.py
 136 test_19_immediate_consistency.py
```

## Tests per queue and instance coverage

- **Queue A (§1.8 depth)**: 68 tests across `test_01`-`test_09`. **21 of 21** non-stub difficulty instances translated; every one carries >=2 tests (minimum-per-instance audit returned an empty under-covered list).
- **Queue B (§1.9 breadth)**: 149 tests across `test_10`-`test_19`. **50 of 50** live corner instances translated (90 `name:` entries total minus 40 `excluded_because:` stubs). Per section: entities 11, state_machines 9, calculations 2, validations 17, endpoints 2, rbac 5, cross_cutting_complexity_layers 3, consistency_model 1.

## Instances skipped

- No live instance was skipped for PRD-silence or non-unique-derivability.
- The 40 `excluded_because:` stubs in queue B were not translated, per the specification; all 40 cross-references were verified to resolve to a live instance that does cover the behaviour.

## PRD-vs-design deviations (design assertion dropped, PRD followed)

1. `Corner/state_machines/discipline_status_advances_while_license_status_holds_and_blocks_inactivation` — design wants `UNDER_INVESTIGATION` + GO_INACTIVE -> 409 `ERR_DISCIPLINE_HOLD`; PRD line 269 bars only `PENDING_HEARING`. Assertion dropped; instance covered by three PRD-derivable tests.
2. `Corner/validations/team_lead_is_required_for_team_kind_and_forbidden_otherwise` — design wants 400 `ERR_INVALID_REQUEST` for a DBA carrying `team_lead_licensee_id`; PRD line 425 gives 422 `ERR_TEAM_LEAD_NOT_AFFILIATED`, which is what `test_13` asserts.
3. `Corner/validations/the_amendment_cap_and_the_statute_deadline_close_the_case_from_two_directions` — design increments `amendment_count` on `REQUEST_AMENDMENT`; PRD lines 347/351 increment only on the complainant's amendment. `test_14` follows the PRD.
4. `Corner/rbac/an_entity_backed_role_may_not_act_on_another_persons_record` — design has an owning `ProviderAdmin` enrol an instructor against a `PENDING` provider and expects 201; PRD line 291 requires `APPROVED` (`ERR_PROVIDER_NOT_APPROVED`). Used an APPROVED provider; rung 6 still precedes the state gate, so the ownership refusal under test is unaffected.
5. `Corner/consistency_model/every_cascade_of_a_write_is_visible_in_that_writes_own_response` — design asserts `open_audit_finding_count == 1` on the brokerage, a field the PRD never defines (its four counters are `affiliated_licensee_count`, `open_shortage_cents`, `open_complaint_count`, `overdue_remediation_count`). Dropped; `test_19` asserts the PRD-defined `open_shortage_cents` and `supervision_posture` instead.

## Verification run

- `python3 -m py_compile` on all 30 files: pass. Runtime import of all 19 test modules under `PYTHONPATH=.`: pass (catches non-existent helper references).
- Verbatim citation check against `workspace/PRD.md`: `checked 238; missing = 0`.
- Design-tag audit: 217 tests, exactly one `Design:` line each, always the last docstring line, every tag resolving to a real `name:` in the source yaml — 0 problems.
- Path rule: `./test_helpers` and `./test_suite` exist at the task root; `ls -d ./workspace/test_helpers ./workspace/test_suite` returns "No such file or directory" for both (`workspace/` holds only `INSTRUCTION.md` and `PRD.md`). Nothing under `workspace/implementation/` was read or written; no sibling task directory was read.
- No `skip`/`xfail` markers and no occurrence of the word "scaffold" anywhere in either directory.

## Step 6: Implementation generation — 2026-09-04T03:27:00Z

Orchestrator verification: `workspace/implementation/` contains `start.sh` plus 16 Python modules and `requirements.txt`. See the Step 5 entry above for the recorded ordering deviation and the isolation mitigation applied to this step.

### Verbatim subagent summary

The implementation is complete.

## Module inventory (`workspace/implementation/`, 3,482 lines)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | guarded `pip install`, `exec python3 app.py` (executable) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 61 | Flask app, 6 blueprints, `ApiError`/404/405/500 handlers, `store.bootstrap()`, `0.0.0.0:$PORT` (default 10000), threaded |
| `store.py` | 196 | in-memory dicts over 15 kinds, logical clock, id/seq minting, `touch`/`insert`, licence & case number counters |
| `errors.py` | 88 | full 62-entry error->HTTP catalogue + `ApiError`/`fail`/`invalid` |
| `envelope.py` | 42 | `meta`/`response_type`/`data` envelope, pagination meta, error envelope |
| `authz.py` | 36 | rung 1 (`ERR_UNAUTHENTICATED`) + rung 2 (`ERR_FORBIDDEN_ROLE`) |
| `shape.py` | 177 | rung 3 body-shape/enum/bounds/ISO-8601 helpers, `paging()` |
| `computed.py` | 356 | enums, all constants, `must()` 404 map, two-basis shortage, posture, CE, reinstatement fee, priority score, name normalisation, provider counters |
| `serialize.py` | 296 | 15 projectors; ledger entries & completions carry only `id`+`created_at` |
| `cascades.py` | 269 | posture snapshot/settle, discipline open/clear, instructor->credit->student chain, suspend/revoke, firm cascade, order issuance, remediation/escalation |
| `routes_read.py` | 292 | all 27 GETs with per-endpoint role lists and declared filters |
| `routes_licensing.py` | 343 | licensee, exam, affiliation/transfer, status changes, brokerage, activation, trust account |
| `routes_trust.py` | 334 | ledger append, audit schedule, fieldwork, disposition, compliance sweep |
| `routes_discipline.py` | 433 | complaint intake/disposition/amendments, consent lifecycle, hearing scheduling/disposition |
| `routes_fund.py` | 279 | fine payments, vacatur, claims, appropriations, award waterfall |
| `routes_education.py` | 271 | providers, instructors, completions, advertising names, clock |

## Endpoint coverage
**60 of 60** — verified by introspecting `app.url_map`: 27 GET + 33 POST.

## Structure
- **State machines** — two independent dimensions on Licensee (`license_status` x `discipline_status`); each transition is an explicit guarded branch in its route, with all system-driven transitions living in `cascades.py` so a hearing decision, a consent execution and a sweep step all reach the same code. `_suspension_order_id` is an internal marker letting sweep step 4 test whether the driving order reached `SATISFIED`.
- **Cascades** — a before/after `posture_snapshot(...)`/`settle(...)` pair implements "when a brokerage's posture *enters* RESTRICTED or FROZEN" generically, and drives the auto-rejection of `SUBMITTED` names with `reviewed_by_user_id` left null. The three normative chains (audit shortage 4-layer, revocation->suspend->close, vacatur 5-step) are written as ordered statements, not helpers.
- **Calculations** — exact integer cents everywhere; `Decimal`+`ROUND_HALF_UP` at exactly the two declared sites (2% assessment; round-then-multiply per-period reinstatement surcharge -> 263/period). Waterfall = first pass with 4-way `min`, then assessment, then a single re-pass shaving only the last `created_at`-ordered candidate and recomputing the assessment once.
- **51 rungs** — the ladder is realised as statement order inside each route; `guard()` (1-2) -> `shape.*` (3) -> `computed.must()` for path (4) then body FKs (5) -> ownership/identity (6-8) -> state (9) -> domain rungs in ascending priority. The three deliberate rung-9 carve-outs (DENIED applicant -> 35, already-open channel -> 39) are coded as pre-checks that fall through to a repeated state check.
- **OCC** — only the three declared parents: `expected_trust_account_version` (mandatory on ledger append), `expected_brokerage_version` (affiliation/transfer), `expected_recovery_fund_version` (disbursement); all 412. One `touch()` per row per request via `flask.g` so a cascade that revisits a row bumps `version` only once.
- **Storage** — module-level dicts only. No file, DB or /tmp state; `bootstrap()` creates only the PRD §2.4 `RecoveryFund` singleton (system initialisation, not entity data).

## Smoke results (port 18635, killed by recorded PID + port check; no pattern kill used)
All green: 401 on missing headers; clock default `2026-08-01T00:00:00Z` and `set_current_utc`; licence mint `BR-000001`/`SP-000001`; exam pass->`EXAM_PASSED`; brokerage register/activate; affiliation issuing `ACTIVE` + `license_expires_at` = +730d; ledger append with correct 412 on a stale version; two-basis figures `900000/500000/400000`; audit schedule -> `ERR_FIELDWORK_NOT_STARTED` before the window then `FIELDWORK` with frozen shortage; `ISSUE_FINDINGS` -> `REMEDIATION_ORDERED` + account `RESTRICTED` + posture `RESTRICTED`; sweep escalation creating `CMP-000002` (TRUST_SHORTAGE, loss 400000, respondent = designated broker) and a second sweep reporting all-zero counters; complaint priority score 90 -> probable cause -> consent accept -> `ERR_SEGREGATION_OF_DUTIES` on self-execute -> execution issuing the order; appropriation 3,000,000; waterfall producing `total=2,450,000 / assessment=49,000 / balance_after=501,000 / shaved_claim_id=<Bob>`; vacatur clawing both claims back to `CLAWED_BACK` with balance 2,951,000 — the fund invariant holds at every step; provider/instructor/completion gates (`ERR_PROVIDER_NOT_APPROVED`, `ERR_NOT_RESOURCE_OWNER`, prelicense hours 30->42 then `ERR_PRELICENSE_HOURS_INSUFFICIENT`); advertising normalisation `"Elm & Oak Realtor"`->`ELMOAKREALTOR` with `prohibited_term_hits=1`, admitted to `SUBMITTED` but `ERR_PROHIBITED_ADVERTISING_TERM` at review, and `ERR_ADVERTISING_NAME_TAKEN` on a colliding normalised form; pagination echo and `limit=0`->1 clamp. A separate `bash start.sh` boot on 18636 returned an empty licensee list, confirming no carry-over state and no seeding.

## Step 7 — test/fix loop (8-round parallel stability sweep)

Three sweeps of 8 concurrent rounds (`--isolation per-test-server`, `--timeout 120`,
`--test-timeout 30`, `setsid nohup` + `wait`).

- Sweep 1: 168/240 in all 8 rounds (72 unique failures, fully deterministic).
- Sweep 2: 237/240 in all 8 rounds.
- Sweep 3: **240/240 in all 8 rounds**.

Implementation fixes:
1. `store.py` — split the ISO-8601 renderers. `fmt_audit()` keeps the three
   fractional digits PRD §2.4 mandates for `created_at`/`updated_at` (and §2.2's
   `api_request_timestamp`); `fmt_dt()` renders a domain instant at exactly the
   instant the logical clock reads (§2.5's mandatory `2026-08-01T00:00:00Z`).
   `insert()`/`touch()` now stamp via `fmt_audit`. (~62 failures.)
2. `envelope.py` — `api_request_timestamp` uses `fmt_audit`.
3. `routes_licensing.py::create_affiliation` — snapshot only the receiving firm,
   per PRD §3.3 "The receiving firm's `version` advances by one, and
   `affiliated_licensee_count` and `supervision_posture` are recomputed on both".
4. `cascades.py::revoke_team_names` — clear `reviewed_by_user_id`, per PRD §3.12
   "revoked by the system ... again with no `reviewed_by_user_id`".

Test-suite fixes (no test deleted, no assertion weakened):
- `test_18_optimistic_concurrency.py` — `bank_available_cents` (a field the PRD
  never defines) → `book_available_cents` (§3.6's stored triple), 3 sites.
- `test_13_validation_gates.py` — removed a stray duplicated positional error id
  in `validate_error`; moved `_bank_twelve_core_hours`' `completed_on` off the
  reactivation date so PRD §3.4's inclusive-window rule and "`ce_hours_valid`
  reads 0 immediately after reactivation" no longer collide.
- `test_10_entity_contracts.py` — compare the audit triple as an instant via
  `parse_instant`, since §2.4 fixes it at three fractional digits.

## Step 7: Test/fix iteration loop — 2026-09-04T04:05:00Z

Orchestrator independent verification (per the known failure mode where a Step 7 agent reports a clean sweep with no artifacts on disk): all 8 `workspace/implementation/results.$i.json` files exist (~83 KB each, Sep 4 03:59) and each parses to `passed=240 total=240 failed=0 errors=0`. Confirmed by the orchestrator, not taken on the subagent's word. (240 collected items vs 217 `def test_` functions is the parametrised-test expansion.)

### Verbatim subagent summary

## Summary

**All 8 parallel rounds are green: 240/240 passed, 0 failed, 0 errors, in every round.**

**Iterations run:** 3 full 8-round parallel sweeps (`setsid nohup`, all 8 launched concurrently and joined with `wait`, no early exit).
- Sweep 1: 168/240 in all 8 rounds (72 unique failures, perfectly deterministic — no reaping signature, no load flakiness)
- Sweep 2: 237/240 in all 8 rounds
- Sweep 3: **240/240 in all 8 rounds**

**Tests deleted:** none. No PRD-silence deletion was warranted — every failure resolved to either an implementation defect or a test artifact that could be made *more* faithful to the PRD. No assertion was weakened, no `skip`/`xfail` added, no error_id downgraded to a bare status check.

**Fixes to `test_helpers/`:** none.

**Fixes to `test_suite/`:**
- `test_18_optimistic_concurrency.py` (3 sites) — `bank_available_cents` -> `book_available_cents`. The PRD never defines `bank_available_cents` anywhere; §3.6's stored triple is `book_obligation_cents`/`book_available_cents`/`shortage_cents`, and the figure asserted is the book figure.
- `test_13_validation_gates.py` — removed a stray duplicated positional error id that made `validate_error` demand `ERR_DESIGNATED_BROKER_NOT_BROKER` where the PRD ladder yields `ERR_DUPLICATE_TRANSACTION_REFERENCE`; and moved `_bank_twelve_core_hours`' `completed_on` from `2026-08-20` (the reactivation date itself) to `2026-08-10`. The old date put two PRD §3.4 sentences in direct conflict — "The window's opening date is inclusive — a course completed on the very day of issuance or reactivation counts" (=> 12) versus "`ce_hours_valid` reads 0 immediately after reactivation" (=> 0). Dating the qualifying completion inside the old window and strictly before reactivation makes both sentences true at once, and preserves the strict `== 0` assertion.
- `test_10_entity_contracts.py` — compare `created_at`/`updated_at` as instants via `parse_instant` instead of as raw strings, since §2.4 fixes the audit triple at three fractional digits (the test, not the implementation, was contradicting the PRD here).

**Fixes to `implementation/`:**
- `store.py` — split the ISO-8601 renderer into `fmt_audit()` (three fractional digits, per §2.4 for `created_at`/`updated_at` and §2.2 for `api_request_timestamp`) and `fmt_dt()` (a domain instant rendered at exactly the instant the logical clock reads, per §2.5's mandatory `2026-08-01T00:00:00Z` startup default). `insert()`/`touch()` now stamp via `fmt_audit`. This one change fixed ~62 of the 72 original failures.
- `envelope.py` — `api_request_timestamp` renders via `fmt_audit`.
- `routes_licensing.py::create_affiliation` — snapshot only the *receiving* firm, per §3.3's within-sentence contrast ("The receiving firm's `version` advances by one, and `affiliated_licensee_count` and `supervision_posture` are recomputed on **both**..."); the departed firm's two figures are read-time-derived, so nothing is written to its row.
- `cascades.py::revoke_team_names` — clear `reviewed_by_user_id`, per §3.12 ("revoked by the system with `rejection_reason` `TEAM_LEAD_INELIGIBLE`, again with no `reviewed_by_user_id`" / "the absence of a reviewer is the audit trail's way of showing no human made that call"). The clearing is confined to the system cascade, so an analyst's manual `REVOKE` still records its reviewer.

**Constraints honored:** `workspace/PRD.md` untouched; storage remains in-memory dicts only (no sqlite, no JSON dump, no `/tmp` cache — verified by grep); no broad pattern kills used; `--api-url` omitted; diagnosis taken only from per-round `results.$i.json`, never from `sweep.log`; failing-test union taken across all 8 rounds each sweep.

**Per-round final results:**

| round | passed/total | duration |
|---|---|---|
| results.1.json | 240/240 | 444.2s |
| results.2.json | 240/240 | 444.2s |
| results.3.json | 240/240 | 444.1s |
| results.4.json | 240/240 | 444.3s |
| results.5.json | 240/240 | 444.2s |
| results.6.json | 240/240 | 444.3s |
| results.7.json | 240/240 | 444.1s |
| results.8.json | 240/240 | 444.3s |

Step 8 is NOT skipped: Step 7 applied 4 `implementation/` fixes and 3 `test_suite/` fixes across 3 iterations, so PRD.md left behaviour underdetermined at those sites.

## Step 8: PRD finalization — 2026-09-04T04:14:00Z

Orchestrator verification: `workspace/PRD_FINALIZED.md` exists, 586 lines / 124,620 bytes (same line count as PRD.md, +2,220 bytes), 4 changed lines (8 diff-side lines), and still ends on the §5 catalogue's final row. Step 8 was not skipped because Step 7 applied 4 `implementation/` fixes.

### Verbatim subagent summary

Done. Verified: both files are 586 lines; `PRD_FINALIZED.md` still ends at the §5 error-catalogue table's final row.

## Line counts
- `PRD.md`: 586 lines / 122,400 bytes
- `PRD_FINALIZED.md`: 586 lines / 124,620 bytes
- Line delta 0.0% (all four edits extend existing sentences in place); byte delta +1.81%

## Changes
- **§2.4** — insert — pinned the rendering split the Step 7 `store.py` fix created: the audit triple and `api_request_timestamp` are the only instants with a fixed fractional part; every other stored/returned instant renders at whole-second precision when it falls on an exact second and only carries three fractional digits otherwise — `implementation/store.py:39-59`, `envelope.py:13`
- **§3.3** — insert — pinned that on an affiliation or transfer only the *receiving* firm's row is stamped; the departed firm re-derives both figures on read and keeps its existing `version`/`updated_at`, with an explicit carve-out noting that parking/expiry/suspension/revocation *do* stamp the firm — `implementation/routes_licensing.py:142-160`
- **§3.12** — insert — pinned that the system team-name revocation cascade clears a previously recorded approver's `reviewed_by_user_id` back to null, and that only the system cascade does so (a manual `REVOKE` still records the analyst) — `implementation/cascades.py:45-59`
- **§3.4** — insert — softened the false universal "`ce_hours_valid` reads 0 immediately after reactivation": nothing is deleted or re-flagged, so a qualifying completion dated on the reactivation date itself (or later) still counts under the inclusive window boundary — `implementation/computed.py:237-249`, `routes_licensing.py:259`

No PRD edit was made for the `bank_available_cents`->`book_available_cents` fix (§3.6 already names the stored triple), the stray duplicated error id in `test_13` (§2.11 ladder already yields `ERR_DUPLICATE_TRANSACTION_REFERENCE`), the `test_13` fixture date move (covered by the §3.4 softening above), or the `test_10` `parse_instant` change (§2.4 already fixed the audit triple at three digits, which is what the impl now does).

## Per-edit pre-edit search log

**Edit 1 (§2.4, instant rendering)**
- (a) Subject: how every instant-valued field is serialized.
- (b) Enumerated: `grep -rn "fmt_dt\|fmt_audit"` across all of `implementation/` — 34 callsites in `store.py`, `envelope.py`, `cascades.py`, `routes_licensing.py`, `routes_trust.py`, `routes_discipline.py`, `routes_fund.py`, `routes_education.py`. Read `store.py:39-65` (`fmt_audit` / `fmt_dt` / `fmt_date`) and all of `serialize.py` to confirm every instant is stored pre-rendered and echoed verbatim (no re-render, no raw client passthrough). Confirmed `insert()`/`touch()` are the only `fmt_audit` writers and `envelope.py:13`. Confirmed date-valued fields (`as_of_date`, `cleared_date`, `effective_date`, `completed_on`, `ce_period_start_on`, `paid_on`, `cleared_through_date`) go through `fmt_date`, not the instant renderer. Cross-checked `test_helpers/clock.py:20-22` and `test_13:26 NEW_TERM_EXPIRY`/`test_10:21 LICENCE_EXPIRY` (second-precision string compares) versus `test_10:524` (audit triple via `parse_instant`) as evidence both forms are observable.
- (c) Adjustment: enumerated the fields explicitly rather than writing a blanket "all timestamps" claim, and kept `fmt_dt`'s fallback branch (`if dt.microsecond`) in the wording — "carries three fractional digits only when the instant does not fall on an exact second" — so a sub-second clock setting is not mis-described. Excluded all date-only fields from the list.

**Edit 2 (§3.3, departed firm not stamped)**
- (a) Subject: which brokerage rows get `touch()`ed (version/`updated_at`) when a licensee stops being one firm's active affiliate.
- (b) Enumerated: `routes_licensing.py::create_affiliation:147-160` (snapshot of receiving firm only); `cascades.py::posture_snapshot`/`add_snapshot`/`settle:9-35` (settle is the only thing that touches firms); `routes_licensing.py::_go_inactive:203,219` (departed firm **is** snapshotted -> touched); `routes_licensing.py::_reactivate:251`; `routes_trust.py::compliance_sweep:252` (expiry snapshots the sponsoring firm), `:288` (default-suspension), `:304` (restore); `cascades.py::apply_order_consequences:161` (snapshots sponsoring firm before `revoke_licensee`/`suspend_licensee` clears or de-activates); `cascades.py::firm_cascade_for_sanction:141`; `computed.py::affiliated_licensee_count`/`supervision_posture` and `serialize.py::brokerage:43-59` (both figures read-derived, and `affiliated_licensee_count` is *not* a posture driver, so the departed firm's posture cannot change on a transfer out). Cross-checked `test_suite/test_14_validation_cascades.py:288-291`.
- (b/c) Adjustment: my first wording said "as §3.4 and §3.13 describe" for the contrasting paths; the sanction-driven suspension/revocation paths live in §3.9/§3.10, so the section pointers were wrong. Rewrote the parenthetical to describe the contrast without section numbers, and scoped the main claim to "on an affiliation or a transfer" so `_go_inactive`, expiry, suspension and revocation are not mis-described.

**Edit 3 (§3.12, clearing `reviewed_by_user_id`)**
- (a) Subject: every write to `AdvertisingName.reviewed_by_user_id`.
- (b) Enumerated: `grep -rn "reviewed_by_user_id" implementation/*.py` — `routes_education.py:206` (intake, null), `:225` (manual `REVOKE`, records actor), `:235` (manual `REJECT`, records actor), `:258` (manual `APPROVE`, records actor), `cascades.py:58` (system team-name revocation, cleared to null), `cascades.py::reject_submitted_names:37-42` (POSTURE_RESTRICTED — does *not* write the field; SUBMITTED rows are already null). Enumerated all four callers of `revoke_team_names`: `create_affiliation:158` (transfer), `_go_inactive:209`, `suspend_licensee:125`, `revoke_licensee:135`, plus `compliance_sweep:258` (expiry) — all are "transfers away or loses `ACTIVE` standing", so the existing §3.12 trigger clause already covers them. Cross-checked `test_07:212`, `test_12:127,142`, `test_04:349`.
- (c) Adjustment: added the explicit "Only the system cascade clears the field this way; an analyst's own `REVOKE` decision records their `X-User-ID`" sentence so the new claim cannot be read as applying to `routes_education.py:225`, and left the POSTURE_RESTRICTED sentence's "stays **null**" wording untouched (that path writes nothing).

**Edit 4 (§3.4, `ce_hours_valid` after reactivation)**
- (a) Subject: `ce_hours_valid` and the `ce_period_start_on` window boundary.
- (b) Enumerated: `computed.py::ce_hours_valid:237-249` (`completed_on >= start`, inclusive; filters on `credit_status == VALID` and `course_type in {CE_CORE, CE_ELECTIVE}`), `computed.py::ce_deficient:270`, `routes_licensing.py::_reactivate:259` (`ce_period_start_on = moment.date()`), `create_affiliation:156` (issuance sets it the same way), `create_licensee:41` (null), `cascades.py::invalidate_recent_completions:86-94` (the only thing that ever flips a completion out of `VALID`), and `routes_education.py` completion reporting (stores the row; the student's figure is purely derived — `serialize.py:33-35`). Cross-checked `test_13:66-78` and `:144-146`.
- (c) Adjustment: phrased the correction as an additive clarification ("Nothing is deleted or re-flagged ... so the one completion that does survive") rather than editing or deleting the "reads 0" sentence, and pointed at "the inclusive boundary described below" so the new sentence derives from — instead of competing with — the existing "How valid hours are counted" paragraph.

## Step 9: PRD completeness scan — 2026-09-04T04:55:00Z

Orchestrator decision (recorded per the AUTONOMY directive): Step 9 was deliberately run as **three sequential, file-partitioned passes** over `implementation/` rather than one monolithic scan. A single-agent full-implementation scan across 17 modules / 3,482 lines has a known failure mode where the agent reports a scan but leaves `PRD_COMPLETED.md` byte-identical to its source — the scan silently never ran. Partitioning gives each pass a tractable slice and makes a no-op detectable. Each pass was told which files the prior passes covered, which behaviours they had already verified as uniquely pinned, and which new pins it must not contradict, so no work was duplicated and no earlier edit was reverted.

- Pass A — `app.py`, `store.py`, `errors.py`, `envelope.py`, `authz.py`, `shape.py`, `computed.py`, `serialize.py`. Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`. 14 changes: 12 ambiguity-pins, 2 mismatch-revisions. 586 -> 590 lines, 124,620 -> 131,702 chars.
- Pass B — `routes_licensing.py`, `routes_education.py`, `routes_read.py`, `cascades.py`. 33 changes: 25 ambiguity-pins, 8 mismatch-revisions. 590 lines held (all in-paragraph), 131,702 -> 151,671 chars.
- Pass C — `routes_trust.py`, `routes_discipline.py`, `routes_fund.py`. 24 changes: 15 ambiguity-pins, 9 mismatch-revisions. 590 -> 596 lines, 151,671 -> 163,385 chars.

**Totals across the scan: 71 changes — 52 ambiguity-pins, 19 mismatch-revisions.**

Orchestrator verification: `workspace/PRD_COMPLETED.md` is 596 lines / 163,385 chars; `cmp` against `PRD_FINALIZED.md` confirms the two files differ (128 diff-side lines), so the scan genuinely ran and did not no-op; the heading count is unchanged at 32, confirming no new sections were introduced; and the document still ends on the §5 catalogue's final row (`| \`ERR_REINSTATEMENT_FEE_MISMATCH\` | 422 |`), i.e. no truncation.

No code was touched in Steps 8 or 9 — `implementation/`, `test_suite/` and `test_helpers/` are exactly as Step 7 left them, so the 8/8 green sweep recorded under Step 7 (240/240 per round) remains the standing result. `results.1.json` … `results.8.json` are on disk under `workspace/implementation/`.

### Notable mismatch-revisions (PRD had described behaviour the implementation does not exhibit)

- §2.11 rung 9 — a fourth carve-out: paying a fine on or vacating an already-`VACATED` order answers rung 12 `ERR_ORDER_ALREADY_VACATED`, not a bare state error.
- §2.4 — `version` advances at most once per row per request, not once per mutation.
- §3.1 — a complaint may be filed against a `DENIED` licensee; the `DENIED` gate sits on the `INVESTIGATE` disposition.
- §3.2 / §3.5 — the claimed uniqueness of brokerage registered names and of provider names does not exist in the implementation; both were dropped.
- §3.4 — expiry is not symmetric with parking: it revokes team names but does not repoint supervisees.
- §3.7 — BOOK-basis `bank_balance_cents`/`cleared_through_date` are stored and echoed rather than ignored; `VERIFY_REMEDIATION` recomputes against the audit's stored dates, not the current clock; the remediation cascade's fourth layer fires only on *newly entering* `RESTRICTED`/`FROZEN`.
- §3.9 — `REVISE` overwrites `proposed_sanction_type` only when supplied.
- §3.10 — the vacatur's five compensations are exhaustive; the PRD's "must unwind every consequence" overclaimed.
- §3.11 — `shaved_claim_id` is recorded whenever the deficit test fires even if the computed shave is 0, and the shave is capped at the last award, so a run can still land below the reserve floor.
- §3.13 step 5 — provider suspension invalidates no completion credits and gathers no brokerage.
- §2.1 / §4 — no `GET` enforces ownership; on a read the role list is the complete authorisation test.
- §3.9 — `ERR_RESPONDENT_MISMATCH`, named in PRD prose, exists in neither the error catalogue nor the implementation; the real answer is `ERR_NOT_RESOURCE_OWNER` (403).

## Pipeline complete — 2026-09-04T04:55:00Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (10 files, 2,555 lines), `test_suite/` (20 files, 8,931 lines, 240 collected tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (start.sh + 16 modules, 3,482 lines) and the eight passing `results.$i.json` sweep records.
