# Worklog — task_2665_wetland_mitigation_banking_credit_sales

## Step 1: Create task directory — 2026-09-04T03:29:50.764Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2665_wetland_mitigation_banking_credit_sales` and `.../workspace` (pre-assigned path from the invocation; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-04T05:22:15.178Z

All three scaffold artifacts are complete and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2665_wetland_mitigation_banking_credit_sales/SCAFFOLD.yaml` | 2743 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2665_wetland_mitigation_banking_credit_sales/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3318 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2665_wetland_mitigation_banking_credit_sales/SCAFFOLD_CORNER_DESIGN.yaml` | 6306 |

## SCAFFOLD.yaml counts (§1.0–§1.7)
- 13 entities (Sponsor, Permittee, IRTMember, MitigationBank, Prospectus, ProspectusVote, WorkPlan, PerformanceStandard, ReleaseMilestone, MonitoringReport, RemedialAction, CreditSale, CreditLedgerEntry)
- 7 state machines, 2 OCC concurrency rules (`quote-create-stale-bank`, `release-approval-stale-bank`)
- 9 calculations, 37 validation rules (priority ladder 1→83), 52 endpoints, 57 errors, 5 roles
- `complexity_profile`: beyond_expert, ledger_reconciliation × multi_party_negotiation, layers = dual_variant_calculation / cascading_side_effects / optimistic_concurrency / derived_field_reconciliation, role_model = segregation_of_duties, consistency_model = immediate
- Top-level keys contain neither `scaffold_difficulty_design` nor `scaffold_corner_design`

## Design instances
- **§1.8** (`scaffold_difficulty_design`): **24 instances** across 9 rule_ids — dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (3), transitive_cascade (2), priority_pair_validation_conflict (3), boundary_precision_check (3), cross_entity_state_dependency (4), resource_temporal_overlap (2), compensating_invariant (2)
- **§1.9** (`scaffold_corner_design`): **90 instances** = 60 full `test_recipe` instances + 30 `excluded_because` stubs, over all 9 claim-extraction-guide sections: entities 10, state_machines 12, calculations 12, validations 14, endpoints 4, errors 23, rbac 6, cross_cutting_complexity_layers 7, consistency_model 2

## Verification
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    52
  §1.1 entities declared:     13
  §1.8 instances scanned:     24
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  1768
```
Additional self-checks: single required top-level key in each design file; 0 duplicate instance names across the union of both design files; all 30 stubs carry no `test_recipe` and cite a `rule_id / instance_name` pair that exists in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; 0 unbound `${...}` placeholders in any `setup_api_calls`, `trigger` or `assert` across both files.

Notes on things caught during authoring of the final sections: two nonexistent read endpoints were removed from asserts/calls (`GET /mitigation/work-plans/{id}` -> `GET /mitigation/banks/{id}/work-plans`, and a `GET /mitigation/prospectuses?bank_id=` collection that does not exist -> `GET /mitigation/banks/{id}/prospectuses`); 13 stub `grounds: [errors[ERR_X]]` entries had to be quoted (`["errors[ERR_X]"]`) because a bare nested bracket breaks YAML flow sequences; and the secondary-service-area quote literal was recomputed to 26001500 cents (the 1.15 price cap binds when the 0.12 secondary premium and 0.08 stewardship surcharge stack), replacing an initially transcribed primary-tier figure.

## Step 3: Copy shared files — 2026-09-04T05:22:31.298Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T05:39:03.907Z

Orchestrator truncation check: `wc -l` = 407 lines; tail ends at a real section boundary (final line is the last §5 error-catalogue table row `| ERR_PERFORMANCE_BOND_INSUFFICIENT | 402 |`), not mid-sentence. No regeneration needed.

Subagent summary (verbatim):

Verification complete. All three Hard Contracts pass and the file is intact.

## Deliverable

`workspace/PRD.md` — **407 lines**, 91,054 bytes, written incrementally (1 Write + 11 `cat >>` appends), never in a single Write.

## Section headings, in order

```
# Wetland Mitigation Banking API — Product Requirements Document
## 1. Introduction
## 2. Global Specifications & System-Wide Principles
  2.1. User and Role-Based Access Control
  2.2. API Response Structure                     (verbatim fixed block)
  2.3. Pagination
  2.4. Common Resource Properties and the Immutable Ledger Record
  2.5. Credit Quantities, Money and Rounding Discipline
  2.6. The Logical Clock, Windows and Interval Semantics
  2.7. Optimistic Concurrency on the Bank Ledger
  2.8. Sales Posture: The Derived Gate on Every Credit Transaction
  2.9. Cascade Discipline and Hierarchical Consistency
  2.10. Request Validation Order
  2.11. The Credit Ledger and Its Conserved Quantities
## 3. Business Logic & Workflows
  3.1. Registering the Parties: Sponsors, Permit Holders and the Review Team
  3.2. Site Selection, Service Area Definition and the Stewardship Endowment
  3.3. Prospectus Submission and the Interagency Review Rounds
  3.4. The Mitigation Work Plan: Hydrology, Planting, Invasive Control and Credit Yield
  3.5. Executing the Instrument, Recording the Easement and Funding the Endowment
  3.6. The Credit Release Schedule: Scheduling, Claiming and Approving Releases
  3.7. Performance Monitoring, Attainment Scoring and Remedial Action
  3.8. Selling Credits: Quoting, Pricing, Reservation and Settlement
  3.9. Reversal, Demand Forecasting, Observability and Closing the Bank
## 4. Endpoint Definitions   (52 rows = all scaffold endpoints incl. POST /_clock/set_current_utc)
## 5. Error Code Catalogue   (57 rows = all scaffold errors)
```

## Tail complete

Final non-empty line is a complete §5 table row, matching the last scaffold error entry:

`| ERR_PERFORMANCE_BOND_INSUFFICIENT | 402 |`

No truncation: every planned heading is present, §4 has 52/52 endpoint rows, §5 has 57/57 error rows.

## Hard Contract reports (per skill: reported here only, never written to any file)

**Contract 1 — Field-Name Coverage: PASS.** 185/185 entity field names (including per-entity `common_fields` expansion; `ProspectusVote` and `CreditLedgerEntry` correctly limited to `id`/`created_at`) appear verbatim in backticks. 97/97 endpoint `input` + `query` identifiers appear verbatim. All nested-object keys covered (`credit_strata`: `stratum_code`, `acres`, `lift_factor`; `performance_standards`: `standard_code`, `comparator`, `threshold_value`, `weight`, `effective_from_year`; `measurements`: `standard_code`, `measured_value`). 86/86 enum and state-machine values reachable. All 57 error IDs appear in §2/§3 prose, not just the §5 table.

**Contract 2 — Rule Coverage: PASS.** All 40 state transitions across 8 state machines expressed with both endpoints named (the 4 `MonitoringReport` entries are `review_status=`-prefixed in the scaffold; both `review_status` and `compliance_status` axes are stated, including the `PASS`/`PARTIAL`/`FAIL` fan-out). All 37 validations present with their full priority ladder rendered as ordered prose in §2.10 in exact scaffold priority order 1->83, including the observable consequence that the posture gate (41) precedes OCC (45). Both OCC rules stated (parent `MitigationBank`, `expected_bank_version`, `ERR_STALE_BANK_VERSION`/412, on quote creation and release approval). All 9 calculations translated with rounding order pinned (per-stratum, per-quarter, per-tier, per-standard, and the two-step provisional->final release), and both dual-variant calculations given their divergence semantics. All endpoint `side_effects` lines covered; every multi-endpoint `applies_to` scope enumerated (recusal across 4 operations, sponsor ownership across 11, posture across 3, easement/stewardship across 2 each). Field-level structured content covered (`corrective_scope` = `REMEDIATE: ` + comma-joined failed codes; `assignment_reference` = permit number / site HUC-8 / credits; HUC-8 as exactly 8 digits; weight sum 1.000; strata length 1..6). Sibling-branch symmetry covered for all decision endpoints (work plan approve/return, report accept/return, release approve/defer, `DEFERRED -> CLAIMED` vs `DEFERRED -> PENDING`, three inspection outcomes, three prospectus finalisation outcomes).

**Contract 3 — §3 Path Purity: PASS.** 535 backticked tokens in §3; 0 begin with `/`, 0 are a bare HTTP method, 0 combine method with path.

## Two scaffold conflicts resolved (worth flagging to the implementer/test author)

1. `MitigationBank.open_quote_count` is defined on the entity as `COUNT(CreditSale WHERE bank_id == this.id AND status IN {QUOTED, RESERVED})`, but the reserve endpoint's `side_effects` says `open_quote_count -= 1` — mutually inconsistent, since a reserved sale is still inside the counted set. The PRD states the derived definition authoritatively and describes reservation as *recomputing* the counter rather than decrementing it, so the prose contains no self-contradiction either way.
2. Bank-closure cascade cancellation reason: the §1.2 state machine says `SPONSOR_WITHDREW` while the endpoint side-effect summary implies `BANK_POSTURE_RESTRICTED`. The PRD follows the state machine (`SPONSOR_WITHDREW`) as the more specific source. Similarly `final_release_credits` is documented as initialising to `0.00` per the entity default rather than `null` per the looser side-effect line.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

---

# Step 5 — Unit test suite generation

## Stage 1 — `test_helpers/` (2347 lines, 9 modules)

`types.py` (442) 27 enums + 13 entity TypedDicts + `CreditForecast`; `ProspectusVote` and
`CreditLedgerEntry` carry only `id`/`created_at`. `api_errors.py` (130) all 58 error ids as a
`(str, Enum)` plus the HTTP-status map registered with the framework via
`set_error_http_status_map`. `api_client.py` (272) `ApiClient(GenericApiClient)` with 57
endpoint methods under the `/mitigation` prefix. `constants.py` (76) every calculation
constant plus the canonical world figures. `test_users.py` (56) shared role headers plus
`make_sponsor_headers` / `make_permittee_headers` / `make_irt_member_headers` identity
builders for the three entity-backed roles. `factories.py` (276) payload builders and the
canonical credit strata / performance standards. `assertions.py` (302) per-entity shape
assertions, `assert_credit_conservation`, `assert_ledger_sequence`, `assert_ledger_shape`,
and precision-aware `assert_credits` / `assert_score` / `assert_cents`.
`fixtures.py` (754) the composite world builders: `setup_draft_bank`,
`setup_bank_under_review`, `setup_executed_bank`, `setup_sellable_bank`,
`setup_sellable_bank_with_second_milestone`, `setup_monitoring_ready_bank`, plus the
end-to-end sale, monitoring and remedial chains.

Two ordering constraints are encoded in the fixtures because they are not obvious from the
endpoint list: prospectus finalisation needs a SUBMITTED-or-APPROVED work plan while work-plan
approval needs an APPROVED prospectus (so the chain is submit-prospectus, submit-work-plan,
vote, finalize-prospectus, decide-work-plan, execute-instrument); and a new milestone's
`window_start` must clear the previous `window_end` by 365 days, giving the ladder
INSTRUMENT_EXECUTION [2026-08-01, 2026-09-01), CONSTRUCTION_COMPLETE [2027-09-01, 2027-10-01),
PERF_YEAR_3 [2028-10-01, 2028-11-01). OCC tokens are read fresh from the server immediately
before each guarded write rather than hard-coded, so cascades that bump `version` do not
break setup.

## Stage 2 — `test_suite/` (12 files, 9429 lines, 175 tests)

Generated by 12 partitioned translators, five over the depth index and seven over the breadth
index. Every test translates exactly one non-stub design instance and carries exactly one
`Design:` line as the last docstring line.

| file | lines | tests |
| --- | --- | --- |
| test_01_credit_and_price_calculations.py | 448 | 11 |
| test_02_review_rounds_and_cascades.py | 949 | 14 |
| test_03_validation_precedence_and_boundaries.py | 812 | 19 |
| test_04_cross_entity_prerequisites.py | 555 | 10 |
| test_05_intervals_and_compensation.py | 724 | 12 |
| test_06_resources_and_ledger_records.py | 868 | 12 |
| test_07_lifecycle_transitions.py | 798 | 14 |
| test_08_derived_quantities.py | 697 | 16 |
| test_09_input_and_state_validations.py | 1194 | 26 |
| test_10_endpoint_actions_and_visibility.py | 690 | 11 |
| test_11_error_triggers.py | 690 | 12 |
| test_12_authority_and_concurrency.py | 968 | 18 |

Depth queue: 66 tests over all 24 instances, every instance at 2 or more. Breadth queue:
109 tests over all 60 non-stub instances, every instance at 1 or more; the 30 stub instances
were not translated. No instance was skipped under the PRD-first filter, and no test uses
`skip`, `skipif` or `xfail`.

## Verification

`python3 -m py_compile` clean on all 21 generated modules. `pytest --collect-only` collects
175 tests. A tag audit resolves every `Design:` tag against the real instance names in the two
indices: 0 untagged, 0 dual-tagged, 0 tags pointing at a non-existent or stub instance. A
citation audit whitespace-normalises all 459 quoted PRD sentences and matches each one
verbatim against `workspace/PRD.md`: 0 misses, 0 uncited tests. `test_helpers/` and
`test_suite/` are at the task root with no stray copies under `workspace/`.

## Design-index defects the translators found, all resolved PRD-first

These are index bugs, not implementation latitude; the tests follow the PRD.

1. Bank-closure cascade: two instances assert `cancelled_reason == BANK_POSTURE_RESTRICTED`,
   but §3.9 pins `SPONSOR_WITHDREW` for closure (`BANK_POSTURE_RESTRICTED` is the FAIL-review
   and remedial-failure reason in §3.7). Tests assert `SPONSOR_WITHDREW`. This is the same
   conflict already flagged during PRD authoring.
2. `final_release_credits == null` on a merely-claimed milestone contradicts §3.6, which opens
   a milestone with `final_release_credits` at 0.00. Three instances carry this; the tests
   assert the PRD-supported neighbours instead.
3. `ERR_INVALID_REQUEST` is asserted at HTTP 422 by two `entities` instances; §5 and §2.3 put
   it at 400. All seven call sites in the suite use 400.
4. `open_quote_count_reconciles_after_cancel_and_reserve` pins the count to 0 after
   reservation, but §3.8 defines the counter over QUOTED *and* RESERVED, so a reserved sale is
   still counted. Test asserts the 1 -> 2 -> 1 -> 1 ladder. Same conflict as flagged in PRD
   authoring.
5. `a_sponsor_cannot_operate_another_sponsors_bank` uses `legal_entity_type:
   NONPROFIT_LAND_TRUST`, which is not one of the three PRD values; substituted `NGO`.
6. Several recipes read the demand index at the same logical instant a sale settles, which
   lands `executed_at` exactly on a half-open quarter boundary the PRD does not disambiguate.
   Affected tests advance the clock so the settlement is strictly inside the window and keep
   every pre-computed literal unchanged.
7. Where an instance asserts a value the PRD genuinely does not uniquely derive (whether a
   `HOLD_PLACED` row is appended when the FAIL cascade finds no non-terminal milestone to
   defer; whether a comma-join is followed by a space), that individual assertion was dropped
   while the instance's primary claim was kept. Nothing was weakened to
   `validate_error_is_one_of`.

---

## Step 5: Generate unit tests — 2026-09-04T06:12:00.000Z

(Note: the Step 5 subagent additionally self-appended its own detailed report above under the heading `# Step 5 — Unit test suite generation`. The block below is the summary it returned to the orchestrator, recorded verbatim per the skill's format.)

The test suite for task 2665 is complete and fully audited.

## Files

`test_helpers/` (task root, 2347 lines): `__init__.py` 39, `api_client.py` 272, `api_errors.py` 130, `assertions.py` 302, `constants.py` 76, `factories.py` 276, `fixtures.py` 754, `test_users.py` 56, `types.py` 442

`test_suite/` (task root, 9429 lines, 175 tests):

| file | lines | tests |
| --- | --- | --- |
| conftest.py | 36 | — |
| test_01_credit_and_price_calculations.py | 448 | 11 |
| test_02_review_rounds_and_cascades.py | 949 | 14 |
| test_03_validation_precedence_and_boundaries.py | 812 | 19 |
| test_04_cross_entity_prerequisites.py | 555 | 10 |
| test_05_intervals_and_compensation.py | 724 | 12 |
| test_06_resources_and_ledger_records.py | 868 | 12 |
| test_07_lifecycle_transitions.py | 798 | 14 |
| test_08_derived_quantities.py | 697 | 16 |
| test_09_input_and_state_validations.py | 1194 | 26 |
| test_10_endpoint_actions_and_visibility.py | 690 | 11 |
| test_11_error_triggers.py | 690 | 12 |
| test_12_authority_and_concurrency.py | 968 | 18 |

## Per-queue counts

- **Queue A (difficulty index):** 66 tests over all **24** instances — every instance at >=2 tests (range 2-4).
- **Queue B (corner index):** 109 tests over all **60** non-stub instances — every instance at >=1 test (range 1-3). The **30** `excluded_because:` stub instances were not translated (5 state_machines, 5 calculations, 3 validations, 13 errors, 1 rbac, 3 cross_cutting).

## Instances skipped

**Zero** instances skipped under the PRD-first filter. Every non-stub instance had a verbatim PRD sentence naming its rule and a uniquely-derivable outcome. No `skip`/`skipif`/`xfail`/placeholder anywhere in the suite. A handful of *individual assertion lines* were dropped where the PRD genuinely does not derive them (noted below), but the owning instance's primary claim is always asserted.

## Verification

- `python3 -m py_compile` clean on all 21 modules; `pytest --collect-only` collects 175 tests.
- Tag audit resolving every `Design:` tag against the real `name:` fields in both indices: **175/175 tests carry exactly one `Design:` line, as the last docstring line, pointing at a real non-stub instance.** Zero untagged, zero dual-tagged, zero dangling or stub-pointing tags.
- Citation audit: **459 quoted PRD sentences, 0 misses, 0 uncited tests** (whitespace-normalised literal match against `workspace/PRD.md`).
- Both directories are at the task root; `workspace/` contains only `PRD.md`, `INSTRUCTION.md` and the parallel generator's `implementation/` — no stray test dirs or worklog copies. No scaffold references in generated code.

## Design-index defects worth your attention (tests follow the PRD, not the index)

1. Bank-closure cascade asserts `cancelled_reason == BANK_POSTURE_RESTRICTED`; PRD §3.9 pins `SPONSOR_WITHDREW`.
2. `final_release_credits == null` on a claimed milestone; PRD §3.6 opens it at `0.00` (3 instances).
3. `ERR_INVALID_REQUEST` asserted at 422 by two `entities` instances; PRD §5 and §2.3 say 400.
4. `open_quote_count` pinned to 0 after reservation; PRD §3.8 counts QUOTED *and* RESERVED.
5. `legal_entity_type: NONPROFIT_LAND_TRUST` is not a valid PRD enum value; substituted `NGO`.
6. Several recipes read the demand index at the exact instant a sale settles, landing on an undisambiguated half-open quarter boundary; those tests advance the clock while keeping every pre-computed literal.

Items 1, 2 and 4 are the same three conflicts the PRD-authoring step independently flagged in the worklog, which is a good cross-check.

---

## Step 6: Generate implementation — 2026-09-04T06:07:00.000Z

The implementation is complete.

## Files (`workspace/implementation/`, 2909 lines total)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | `set -euo pipefail`, `cd $(dirname $0)`, guarded `pip install` (only if `import flask` fails), `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 56 | Blueprint registration, `ApiError`/`HTTPException`/500 handlers, `0.0.0.0:$PORT` (default 10000), no reloader |
| `util.py` | 115 | Logical clock (default `2026-08-01T00:00:00Z`), ISO-8601 3-frac-digit formatting, `req_` ids, round-half-up / ceil helpers |
| `errors.py` | 88 | All 57 catalogue codes -> HTTP status (verified byte-for-byte against PRD §5: 0 mismatches, 0 missing, 0 extra) |
| `response.py` | 42 | Success/list/error envelopes; `has_more = offset+len(rows) < total_count` |
| `store.py` | 45 | In-memory dicts only, all boot empty; `new_row`/`touch`/`ordered` |
| `auth.py` | 76 | Header auth, role gate, member resolution, recusal, ownership |
| `validation.py` | 180 | Schema validators, pagination, filters |
| `calc.py` | 224 | Every pinned calculation (credit yield, endowment capitalisation, tiered pricing, demand index, attainment, forecast) |
| `ledger.py` | 227 | Append-only ledger, four aggregates as projections, posture ladder, cascades, rollups |
| `serialize.py` | 240 | One serializer per entity; all derived fields projected at read time |
| `lookup.py` | 52 | Path/FK resolution with entity-specific 404s |
| `routes/` | `parties.py` 108, `banks.py` 268, `review.py` 326, `releases.py` 191, `monitoring.py` 360, `sales.py` 285, `clock.py` 17 |

**Endpoints: 52 implemented / 52 in the PRD** (verified by enumerating the Flask URL map: exactly the 52 method+path pairs of §4, no extras). Every `.py` file compiles under `python3 -m py_compile`. A grep confirms no `sqlite`, `open(`, `json.dump`, `/tmp` or `pickle` anywhere — storage is pure in-memory dicts and every collection is empty at boot; nothing is seeded.

## Notable interpretation decisions (PRD prose wins where sources conflict)

1. **§2.10 ordering beats narrative ordering.** §3.6 narrates the stewardship gate *before* the ecological gate on `approve-release`, but §2.10 pins fiscal checks last ("a caller should learn that the ecology or the paperwork is wrong before learning that the account is short"). Implemented as: state -> OCC -> easement -> SoD -> `ERR_NO_ACCEPTED_MONITORING_REPORT`/`ERR_COMPLIANCE_FAILED` -> `ERR_STEWARDSHIP_UNDERFUNDED`. Same principle on quote creation: the obligation ceiling (`ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT`, referential) is checked before `ERR_INSUFFICIENT_CREDITS` (fiscal), inverting §3.8's prose order.
2. **`return_reason` is a schema-stage requirement** on both `work-plans/{id}/decide` and `monitoring-reports/{id}/review`, so its absence yields 400 before any 409 — §3.4 calls it "a malformed request".
3. **Bank version bumps only where the PRD says so.** Assignment, withdrawal and the lazy expiry sweep append ledger entries or change derived tallies but the PRD never states a version increment for them, so they do not bump; quote/reserve/execute/reverse/release-approval/instrument/easement/contribution/close/report-acceptance/cascades do. Permittee rows are likewise not touched by sale settlement (their money fields are projections).
4. **Report acceptance always bumps the bank version** (the PRD explicitly says the RETURN branch does *not*, which implies the ACCEPT branch does).
5. **`held_credits` = released - sold, evaluated after hop 3**, but forced to `0.00` when the deferred milestone had never been claimed or when no deferrable milestone exists; `HOLD_PLACED` is appended only when > 0.
6. **Deferral candidate** = earliest milestone in `PENDING` or `CLAIMED` (the only source states the transition table defines), ordered by `window_start` ASC with creation order as tie-break. Restoration goes to `CLAIMED` iff `claimed_at` is non-null, and only when no other non-terminal action remains on the bank.
7. **`CLOSED` is terminal for every write**, including the otherwise-reachable work-plan submit/decide path on a closed bank. Close cancels open sales with `SPONSOR_WITHDREW`; the remedial-failure and posture cascades use `BANK_POSTURE_RESTRICTED`.
8. **Bank-scoped projections resolve the bank id before filters/pagination** (§2.11); every other list endpoint validates schema first (§2.10).
9. **Bank closure rejects remedial actions in `FAILED` too** (§3.9 names all four states; the scaffold state machine omitted `FAILED`).
10. **JSON shapes**: credits/scores are JSON numbers via `float(Decimal)` (so `20.00` renders as `20.0`), money is always integer cents; booleans and strings are rejected for numeric fields while integral floats are accepted.

## Smoke test

Launched on port 18265 via `PORT=18265 bash start.sh`, exercised with two end-to-end scripts (50 and 83 assertions), then killed by recorded PID only — no pattern-kill was used against other pipelines.

- Envelope shape confirmed against §2.2 for object, array and error responses, plus 401/403/400/404/409/412/422/402 paths.
- Full happy path: sponsor -> permittee -> 3 members -> bank -> prospectus (round-1 `REVISION_REQUESTED` on a failed supermajority, round-2 `APPROVED`) -> work plan (RETURN -> resubmit -> APPROVE, 2 standards materialised) -> instrument execution -> easement -> endowment -> milestones -> claim -> release -> quote -> reserve -> execute -> assign -> monitoring -> closure.
- Verified numerically: endowment `1,000,000 -> 27,066,667` cents; per-stratum credit yield `20.00`; ESTUARINE 20-credit SECONDARY underfunded price `111,435,000` (the 1.15 cap binding over the 116,280,000 gross); `PARTIAL`/`FAIL` scoring (`0.2250` -> `FAIL`, `1.0000` -> `PASS`); the FAIL cascade landing on released 8.00 = sold 4.00 + hold 4.00 + available 0.00 with `deferral_count` 1 and the milestone `DEFERRED`; clearance restoring available to 4.00 and the milestone to `CLAIMED`; SoD then blocking the clearing member; hold surviving at the exact expiry instant and lapsing to `EXPIRED`/`HOLD_EXPIRED` once the clock passes it; reversal restoring the ledger balance exactly and returning full escrow while retaining `executed_price_cents`.
- The pinned two-entry settlement order (`HOLD_RELEASED` then `SOLD`, consecutive sequence numbers, different running balances) and `credits_available == balance_after` of the highest entry held in every ledger dump.

---

## Step 7: Run tests and iterate — 2026-09-04T06:40:45.395Z

Verified with my own eyes: all 8 `results.*.json` exist and each shows `passed == total == 175`, with `failed=0`, `errors=0`, `skipped=0`.

## Summary

**Iterations run:** 1 (single 8-round parallel sweep, all green on the first pass)

**Sweep result:** 175/175 passing in every one of the 8 concurrently-launched rounds (~326 s per round). No flakiness signal — the union of failing tests across all 8 rounds is empty. No test was skipped or errored, and there are no `skip`/`xfail` markers anywhere in `test_suite/`.

**Tests deleted:** none. STEP 0 produced an empty failure union, so the PRD-coverage / unique-derivability protocol (STEPs 1-3) had nothing to adjudicate.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none required.

Notes for the caller:
- The sweep was run under `setsid nohup` as mandated, so no round was reaped; all 8 per-round JSON files were produced and parsed independently (`sweep.log` was not used for diagnosis).
- Artifact under test: 12 test modules (~11.8k lines across `test_suite/` + `test_helpers/`) against a Flask implementation split into `routes/{banks,review,releases,monitoring,sales,parties,clock}.py` plus `calc.py`/`ledger.py`/`serialize.py` helpers.
- Sweep artifacts left in place for inspection: `workspace/implementation/results.1.json` ... `results.8.json` and `workspace/sweep.log`.

### Orchestrator independent verification (per the known "Step 7 claims a clean sweep with no artifacts" failure mode)

Re-checked the artifacts myself rather than trusting the subagent's claim:
- All 8 `results.$i.json` present, each ~54.8 KB, all timestamped 06:26.
- Parsed each independently: every round reports `passed=175 failed=0 errors=0 skipped=0 total=175`.
- `grep` for `xfail` / `mark.skip` / `pytest.skip` across `test_suite/` and `test_helpers/`: 0 hits.
- 175 test functions, 175 `Design:` tags — one tag per test, matching the Step 5 audit.

## Step 8: Finalize PRD — SKIPPED — 2026-09-04T06:40:45.395Z

Skip condition from the skill met exactly: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the implementation exhibits at every site the test suite exercised, and there is no `<step_7_diff>` to hand off. No subagent spawned; `PRD_FINALIZED.md` is intentionally absent. Step 9 will consequently start from `PRD.md`, and it carries the full burden of closing residual silences the test suite never asserted (the Step 6 subagent self-reported 10 such interpretation decisions, which Step 9 must independently rediscover from `implementation/` since it is barred from reading this worklog).

---

## Step 9: Complete PRD — 2026-09-04T07:10:00.000Z

Run as **three sequential file-partitioned passes** over `workspace/implementation/` rather than one monolithic scan, because a single-agent full-impl scan reliably under-covers a 2900-line implementation (and in the worst case emits a `PRD_COMPLETED.md` byte-identical to its source, i.e. the scan never really ran). Source was `PRD.md` since Step 8 was skipped. Partition, by owning file:

- **Pass 1** — `routes/parties.py`, `routes/banks.py`, `routes/review.py`, `auth.py`, `validation.py`, `lookup.py`, `response.py`, `errors.py`, `store.py`, `app.py`, `util.py`. Did the `cp PRD.md PRD_COMPLETED.md`.
- **Pass 2** — `routes/releases.py`, `routes/monitoring.py`, `calc.py`, `ledger.py`.
- **Pass 3** — `routes/sales.py`, `routes/clock.py`, `serialize.py`, plus a whole-document integrity + cross-pass consistency check.

Each pass could read any impl file for context but could only author edits whose primary subject lived in its own files, so no subject was patched twice or contradicted across passes.

### Totals

`PRD.md` 407 lines / 91,054 chars -> `PRD_COMPLETED.md` 409 lines / 107,148 chars (**+2 lines, +16,094 chars, +17.7%**). **43 diff hunks** at `--unified=0`. Nearly every edit is in-paragraph; one two-line paragraph insertion (§2.2 transport errors); zero new sections, zero deletions.

**Counts: 51 ambiguity-pins, 6 mismatch-revisions, 2 cross-pass consistency repairs.** (Pass 1: 22 pins / 2 mismatches over 24 hunks. Pass 2: 16 pins / 2 mismatches over 13 hunks. Pass 3: 13 pins / 2 mismatches + 2 repairs.)

### Pass 1 changes (parties/banks/review + infrastructure)

- §2.1 — revise — ambiguity — whitespace-only header value counts as empty; values are trimmed — `auth.py:38-48`
- §2.1 — insert — ambiguity — acting-IRTMember resolution happens after schema validation and after all path/parent resolution, before the recusal check — `auth.py:51`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters — `util.py:64`
- §2.2 — revise — **mismatch** — `api_request_timestamp` comes from real wall-clock time, not the logical clock — `response.py:17`
- §2.2 — insert (new paragraph) — ambiguity — out-of-catalogue transport errors: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, unparseable/non-object body -> `ERR_INVALID_REQUEST` 400 with `Content-Type` never a ground for rejection, `ERR_INTERNAL` 500; trailing slashes ignored — `app.py:19,31-46`, `validation.py:16-24`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; empty-string value treated as omitted — `validation.py:138-160`
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation order (matters because the logical clock makes ties the norm) — `store.py:39-41`
- §2.5 — insert — ambiguity — quantities/cents are JSON numbers not strings; output is shortest numeric form (2.50 -> `2.5`); trailing zeros don't count against decimal-place limits — `util.py:106-115`, `validation.py:84-96`
- §2.6 — revise — **mismatch** — "every timestamp" narrowed to timestamps stamped onto stored rows (envelope excepted); client timestamps accept `Z`/offset and a zoneless value is read as UTC — `util.py:39-52`, `response.py:17`
- §2.10 — insert — ambiguity — explicit JSON `null` counts as absent (required -> missing-field, optional -> default); integer fields accept a number with zero fractional part — `validation.py:27-32,60-72`
- §3.1 — insert — ambiguity — a zero-cent deposit is well-formed, still bumps `version`; nothing else gates a deposit — `routes/parties.py:72-77`
- §3.2 — insert — ambiguity — `site_name` <=160 chars; body `sponsor_id` resolved first (404) then must equal the acting sponsor (`ERR_NOT_BANK_SPONSOR`) — `routes/banks.py:42,55-58`
- §3.3 — insert — ambiguity — prospectus drafting admissible for any bank status but `CLOSED`; a bank may carry several prospectus rows — `routes/review.py:36`
- §3.3 — insert — ambiguity — the bank-status and service-area gates apply to first submission only; resubmission re-checks neither and leaves the bank row untouched — `routes/review.py:61-79`
- §3.3 — insert — ambiguity — only the first vote of a round touches the prospectus row; tallies are read-time projections — `routes/review.py:111-114`, `serialize.py:99-102`
- §3.3 — insert — ambiguity — no finalisation branch touches the bank row (no status move, no `version` bump) — `routes/review.py:148-153`
- §3.4 — revise — ambiguity — plan-level standard entries: code from the four-member enum, comparator `GTE`/`LTE`, `threshold_value` with no decimal-place limit, `effective_from_year` must be a JSON integer (not `3.0`) — `routes/review.py:205-218`
- §3.4 — insert — ambiguity — already-approved test precedes the weight-sum test; drafting admissible for any bank status but `CLOSED` — `routes/review.py:235-242`
- §3.4 — insert — ambiguity — "restores nothing" submission gate is rejected with `ERR_WORK_PLAN_STATE_INVALID` — `routes/review.py:271-273`
- §3.4 — insert — ambiguity — work-plan `return_reason` <=1000 chars — `routes/review.py:289`
- §3.5 — insert — ambiguity — `deed_reference` non-empty, <=200 chars; re-recording overwrites, re-stamps and bumps `version` again — `routes/banks.py:122-129`
- §3.5 — revise — ambiguity — `CLOSED` is the *only* status failing the "admits further work" test for easement/stewardship (and for prospectus drafting, work-plan draft/submit/decide); `DRAFT` is accepted — `routes/banks.py:30-33,125,140`
- §3.9 — insert — ambiguity — credit-forecast body is exactly those eight figures, with no `id` or bookkeeping properties — `routes/banks.py:259-268`
- §3.9 — insert — ambiguity — filter semantics: empty string = absent; bad enum value -> `ERR_INVALID_REQUEST`; unknown identifier filter -> empty page, `total_count` 0 — `validation.py:163-176`
- §3.9 — insert — ambiguity — a bank with no milestones satisfies the closure completeness test vacuously — `routes/banks.py:156`
- §4 — insert — ambiguity — unknown body members ignored everywhere; body-less transition endpoints never parse a body (withdrawal excepted, it carries `cancelled_reason`) — `routes/review.py:53`, `routes/banks.py:86,148`, `routes/sales.py:117,155,190,219,244`

Pass 1 note: closure error precedence in §3.9 prose (milestones-then-easement) reads backwards versus the implementation, but §2.10 already pins easement before `ERR_MILESTONES_INCOMPLETE` and the implementation matches §2.10, so both were left alone.

### Pass 2 changes (releases/monitoring/calc/ledger)

- §3.6 — revise — ambiguity — a `predecessor_milestone_id` resolving to a milestone of a *different* bank is also `ERR_MILESTONE_NOT_FOUND` — `routes/releases.py:41`
- §3.6 — insert — ambiguity — milestone scheduling is admissible against any bank status other than `CLOSED` (so schedules may predate instrument execution) — `routes/releases.py:45`
- §3.6 — insert — ambiguity — on claim, the milestone's own state test precedes the bank-status test — `routes/releases.py:89`
- §3.6 — revise — **mismatch** — the window's exclusive `window_end` is descriptive only and is **not** a claim gate; only the lower bound is enforced, so a claim after `window_end` is still accepted — `routes/releases.py:94`
- §3.6 — insert — ambiguity — claiming writes only the milestone row; bank `updated_at`/`version` unchanged — `routes/releases.py:102-107`
- §3.6 — insert — ambiguity — neither bank lifecycle status nor `sales_posture` gates approve-release (a `SUSPENDED` bank can still release) — `routes/releases.py:110`
- §3.7 — insert — ambiguity — `measured_value` is constrained by no decimal-place limit — `routes/monitoring.py:53`
- §3.7 — insert — ambiguity — opening a monitoring report is admissible against any bank status other than `CLOSED` — `routes/monitoring.py:84`
- §3.7 — insert — ambiguity — on submit, the report's own state test precedes the bank-status test — `routes/monitoring.py:126`
- §3.7 — insert — ambiguity — every acceptance bumps the bank's `version` by one regardless of compliance outcome or lifecycle move — `routes/monitoring.py:184`
- §3.7 — insert — ambiguity — bulk open-sale cancellation visits sales in default row order (`created_at` asc, creation-order tie-break), fixing `HOLD_RELEASED` sequence numbers — `ledger.py:185`
- §3.7 — revise — ambiguity — the deferral candidate set is exactly `PENDING`/`CLAIMED`; `DEFERRED` and `APPROVED` are ineligible — `ledger.py:200`
- §3.7 — insert — ambiguity — hop 4 is a no-op when no eligible milestone exists (null `deferred_milestone_id`, no `deferral_count` bump, 0.00 held, no entry) — `routes/monitoring.py:209`
- §3.7 — revise — **mismatch** — the "on hold == held_credits, available == 0.00" consequence was a false universal; qualified to the no-outstanding-earlier-hold case and the released-minus-sold formula's un-netted behaviour pinned (available goes negative by the earlier hold) — `routes/monitoring.py:220`
- §3.7 — insert — ambiguity — a `CLEARED` inspection performs no restoration while another non-terminal action stands, yet still increments the bank's `version` — `routes/monitoring.py:319`
- §3.8 — insert — ambiguity — the expiry sweep never touches the bank row, so an `expected_bank_version` read before a lapse still matches — `ledger.py:167`
- §3.8 — insert — ambiguity — demand quarters exclude their end instant, so a sale settled at exactly the current clock contributes nothing — `calc.py:121`
- §3.9 — revise — ambiguity — the trailing 360-day forecast window is half-open (start included, clock instant excluded) — `calc.py:138`

Pass 2 verified-as-already-pinned (left alone after line-by-line check): all of `calc.py`'s rounding orders (per-stratum, per-quarter, per-standard contribution at 4 places, tiered subtotal, combined-premium single rounding, cap binding order, two-step provisional->final release, single-pass stewardship capitalisation with `ceil` base + half-up fee), interim/full stewardship gate selection, attainment ratio/met semantics for `GTE`/`LTE`, compliance thresholds, `governing_report` selection, ledger aggregate projections and the `sales_posture` ladder, and all list filters/orderings in `releases.py`/`monitoring.py`.

### Pass 3 changes (sales/clock/serialize)

- §3.8 P1 (sweep) — revise — **mismatch** — PRD claimed the expired-hold sweep runs "before anything else happens"; impl runs it *after* auth, schema, identifier resolution and ownership checks and *before* the sale's own state test, so a request rejected on identity/ownership performs no sweep at all — `routes/sales.py:70,120,158,193,224,246`
- §3.8 P1 (sweep) — insert — ambiguity — nothing outside the six credit-sales writes sweeps: reads report a lapsed hold as still `RESERVED` with credits still on hold, and the §3.7/§3.9 bulk cancellations cancel a lapsed reservation outright rather than expiring it first — `routes/sales.py` call sites vs none in `routes/banks.py`, `routes/monitoring.py`
- §2.8 — insert — ambiguity — assignment, withdrawal and reversal are not posture-gated at all (any posture, `FROZEN` included) — `routes/sales.py:187,216,241`
- §2.7 — insert — ambiguity — `expected_bank_version` is schema-constrained to a non-negative integer (negative => `ERR_INVALID_REQUEST`); `0` is always a stale-version rejection — `routes/sales.py:64`, `routes/releases.py:114`
- §3.8 P2 (quote) — insert — ambiguity — body foreign keys resolved bank-then-permittee, so both unknown => `ERR_BANK_NOT_FOUND` — `routes/sales.py:66-67`
- §3.8 P2 (quote) — insert — ambiguity — obligation ceiling is tested before the availability ceiling, so a quote breaching both yields `ERR_ASSIGNMENT_EXCEEDS_REQUIREMENT` — `routes/sales.py:80-85`
- §3.8 P3 (quote opens) — revise — **mismatch** — `quoted_demand_index` was described as "a snapshot of the bank's service-area demand pressure"; impl stores the normalised/capped/4-dp **index**, not the raw weighted pressure — `routes/sales.py:87`, `ledger.py:222`
- §3.8 P6 (two runs) — insert — ambiguity — the executed variant refreshes only stewardship state and demand index; quantity, `hgm_class` and the frozen `service_area_tier` are reused (no service-area re-test), and the measurement is taken while the sale is still `RESERVED` so it never inflates its own re-pricing — `routes/sales.py:47-52`
- §3.8 P7 (reservation) — insert — ambiguity — the hold-overlap candidate set is the buyer's other sales standing in `RESERVED` across **every** bank; all other statuses ignored — `routes/sales.py:128-133`
- §3.8 P8 (settlement) — insert — ambiguity — a settlement past the expiry instant finds the sale already swept to `EXPIRED` and is rejected `ERR_SALE_STATE_INVALID`; there is no distinct lapsed-hold code — `routes/sales.py:160-164`
- §3.8 P9 (assignment) — insert — ambiguity — `assignment_reference` renders the credit quantity with exactly two decimals (`/2.50`, `/3.00`), overriding §2.5's shortest-form rule inside the string — `routes/sales.py:205-207`, `util.py:102`
- §3.8 P9 (assignment) — insert — ambiguity — assignment writes only the sale row: bank `updated_at`/`version` unmoved despite the ledger append, and the buyer's row unwritten; settlement likewise; an escrow deposit is the only write to a permit-holder row after registration — `routes/sales.py:203-212`, `routes/parties.py:75-76`
- §3.8 P10 (withdrawal) — insert — ambiguity — neither withdrawal branch writes the bank row — `routes/sales.py:229-236`
- §2.6 (clock) — insert — ambiguity — `to_iso8601` is required on a required JSON body; the call answers HTTP 200 with `data` carrying `current_utc` as its sole member — `routes/clock.py:12-17`
- §3.9 P3 (observability) — insert — ambiguity — no read anywhere is ownership-filtered; §2.1's ownership checks guard writes only, so no read ever yields `ERR_NOT_BANK_SPONSOR`/`ERR_NOT_SALE_PERMITTEE` — verified across all route files: zero ownership calls in any GET

### Cross-pass consistency repairs (Pass 3, integrity check (d))

1. §2.1's Permittee clause said "ownership checks compare `X-User-ID` to the sale's `permittee_id`" with no write qualifier, while the Sponsor clause said "a Sponsor **write**". Read literally it would mandate ownership-filtered sale reads, which impl does not do. Fixed with a two-word change: "ownership checks **on writes** compare...".
2. §3.9's credit-forecast sentence (Pass 1's insert) said "Those eight figures are the whole of the **response body**", contradicting §2.2's mandatory `meta`/`response_type`/`data` envelope. Fixed to "the whole of the response's `data` object".

Verified consistent, no change needed: the five bank-`version`-increment claims in §3.8/§3.9 (quote, reserve, execute, reverse, close) plus the two new negatives (assign, cancel) match impl's `store.touch(bank)` call sites exactly; §2.8's "ungated" addition does not collide with §3.6's "neither status nor `sales_posture` gates the approval"; §3.8's ordering claims agree with §2.10's pipeline; all `sweep`/`EXPIRED` mentions are confined to §3.8.

### Orchestrator independent verification of Step 9

Checked the output myself rather than trusting the pass summaries (the known failure mode is a `PRD_COMPLETED.md` byte-identical to its source, meaning the scan never ran):
- `cmp PRD.md PRD_COMPLETED.md` -> **differs**. 407 -> 409 lines, 91,054 -> 107,148 chars.
- `diff -U0` hunk count: **43**.
- Tail intact, ending on the real final §5 row `| ERR_PERFORMANCE_BOND_INSUFFICIENT | 402 |` — not mid-sentence.
- Table integrity re-counted independently: §4 = **52** endpoint rows, §5 = **57** error rows — both unchanged from `PRD.md`.
- `find` over `test_helpers/`, `test_suite/` and `workspace/implementation/` for anything modified after the 06:26 green sweep (excluding `results.*.json`): **zero hits**. Step 9 touched only `PRD_COMPLETED.md`, so the 8/8 x 175/175 sweep result still describes the shipped implementation and test suite.
- No stray `worklog.md` copies anywhere in the task tree; no `test_*` directories under `workspace/`.

## Pipeline complete

Final state: `SCAFFOLD.yaml` + both design indices at the task root; `test_helpers/` (9 modules, 2347 lines) and `test_suite/` (12 modules + conftest, 9429 lines, 175 tests, 175 `Design:` tags, 0 skip/xfail) at the task root; `workspace/` holding `INSTRUCTION.md`, `PRD.md`, `PRD_COMPLETED.md`, `sweep.log` and `implementation/` (2900 lines across 12 modules + 7 route blueprints, 52/52 endpoints, in-memory only, nothing seeded) with `results.1.json` ... `results.8.json` all at 175/175. `PRD_FINALIZED.md` is intentionally absent (Step 8 skipped, 0 Step 7 fixes).
