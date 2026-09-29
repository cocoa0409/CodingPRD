# Worklog — task_2719_landfill_airspace_cell_development_management

## Step 1: Create task directory — 2026-09-04T11:34:00.000Z

Created `tasks/task_2719_landfill_airspace_cell_development_management/` and `tasks/task_2719_landfill_airspace_cell_development_management/workspace/`. Index pre-assigned by the orchestrating command (2719); no auto-allocation scan performed, per instruction that up to 32 pipelines run concurrently on this host.

## Step 2: Generate scaffold — 2026-09-04T13:40:00.000Z

Scaffold generation for task_2719 is complete. All three files are in `/home/ubuntu/github/CodingPRD/tasks/task_2719_landfill_airspace_cell_development_management/`, all parse under `yaml.safe_load`, and the linter is clean:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    82
  §1.1 entities declared:     13
  §1.8 instances scanned:     28
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  980

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Worklog-ready summary:

- **SCAFFOLD.yaml** (3190 lines): 13 entities (Landfill, Cell, LinerQaPackage, AerialSurvey, OperatingDay, WasteLoad, SpecialWasteApproval, TreatmentAgreement, LeachateShipment, GasWell, SurfaceEmissionScan, ClosureCostEstimate, HostCommunityAgreement — flat topology, all `common_fields: true`), 13 state machines (cyclic: QA return/resubmit, HCA amendment loop, day close/amend, well tuning loop; WasteLoad carries independent screening + billing dimensions), 2 concurrency rules (OCC on `Landfill.version` only), 11 calculations, 28 ordered validations, **82 endpoints**, **50 errors**, 8 roles (`role_model: segregation_of_duties`, two entity-backed roles keyed on the Landfill id).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (3386 lines): 9 difficulty rules / **28 instances** (2/3/3/3/4/4/4/2/3), every rule >=2.
- **SCAFFOLD_CORNER_DESIGN.yaml** (3180 lines): 9 sections / **72 instances** = 41 full test recipes + 31 `excluded_because` stubs — entities 10+1, state_machines 8+8, calculations 2+12, validations 4+5, endpoints 3+2, errors 7, rbac 4, cross_cutting_layers 2+3 (both OCC rules real), consistency_model 1 (`immediate`). All 31 stub citations resolve to §1.8 names by bare `name` (28 normalised from `rule / name`).
- **Coverage audit**: all 50 error ids are triggered — a trailing comment block in SCAFFOLD_CORNER_DESIGN.yaml maps each id to the instance that reaches it. Bulk-action row intentionally has no instance (§1.5 declares no bulk endpoint; a comment records why). Immutability row skipped (no `common_fields: false` entity).
- **Four scaffold reconciliations made while writing §1.9** (all in SCAFFOLD.yaml): (1) ERR_HOST_AGREEMENT_ALREADY_LIVE made reachable — execute is blocked only when another agreement is UNDER_AMENDMENT, a merely EXECUTED one is superseded/TERMINATED; (2) oxygen boundary aligned — GasWell tune now requires `oxygen_pct < 12.0` so rung 15's `>= 12.0` critical threshold is not contradicted at exactly 12.0; (3) rung-9 carve-out added so a repeat `open-amendment` reports ERR_AMENDMENT_IN_PROGRESS instead of ERR_INVALID_STATE_TRANSITION; (4) added `Cell.final_cover_reference` (source: input, default null) because `POST /cells/{cell_id}/close` accepted the reference with nowhere to store it, and aligned the §1.2 `FULL_to_CLOSED` side effects with §1.5 (final cover stored, landfill airspace recompute, `Landfill.version` +1, with the note that CLOSED stays in the certified set but leaves the closure-cost basis).

## Step 3: Copy shared files — 2026-09-04T13:40:54.000Z

Copied `INSTRUCTION.md` from the project root to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T13:59:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — 508 lines, 115,350 bytes, written incrementally via chunked `cat >>` heredocs (no single giant Write). Ends cleanly on the final `ERR_FINANCIAL_ASSURANCE_SHORTFALL | 402` row of §5 with a trailing newline, no audit footer, no contract-report section.

**Structure:** §1 Introduction (3 paragraphs) · §2 with ten domain-derived subsections (2.1 RBAC · 2.2 API Response Structure, byte-exact copy of `section-2.2-response-structure.md`, verified `in` the file as an exact substring · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Airspace Ledger and Cascade Discipline · 2.6 Measurement Precision and Rounding · 2.7 The Three Site Posture Fields · 2.8 Optimistic Concurrency · 2.9 The Order in Which a Request Is Refused, all 28 rungs · 2.10 Nested Paths and Flat References) · §3 with eleven subsections (3.1-3.11) · §4 endpoint table · §5 error catalogue.

**Hard Contract 1 — Field-Name Coverage: PASS.** 139 unique names harvested mechanically from `entities[].fields[]`, every endpoint `input`/`output`, and every `{path_param}` (optional `?` markers stripped). **0 missing.** Three gaps found and repaired during verification: `generator_name`, `waste_code` and `decision_reason` were absent because the `SpecialWasteApproval` request/approve/deny/revoke lifecycle had no home — a new opening block was added to §3.5 (retitled "Special-Waste Profiles and Waste Acceptance Screening at the Scale House") covering the request fields, both terminal decisions, revocation from `APPROVED`/`SUSPENDED`/`EXHAUSTED`, and the note that `SUSPENDED`/`EXHAUSTED` are cascade-only. All 13 entity type names now also appear literally (added as an enumeration in §2.4), and all 8 role names appear.

**Hard Contract 2 — Rule Coverage: PASS.** All 11 calculations narrated in prose with pinned rounding orders and the forbidden alternates called out; all 28 validations present as ordered rungs in §2.9 with their error ids, statuses and `applies_to` enumerations; all 59 state-machine transitions across 12 machines covered (every one of the 46 distinct state names appears; the 13 that don't render as a literal `X -> Y` arrow are the system-cascade ones described in cascade-link/compensation form — approval `SUSPENDED`/`EXHAUSTED` and their unwinds, survey `SUPERSEDED -> RECORDED` restore, agreement lazy `EXPIRED`, gas `CONNECTED -> ONLINE`/`TUNING_REQUIRED` branch, scan `PASSED`/`EXCEEDANCE_OPEN`, estimate `STALE`/`SUPERSEDED`); both `concurrency_rules` in §2.8. A missing explicit `PROVISIONAL -> FINALIZED` billing-dimension statement was found and added to §3.7. Constant sweep: of 84 numeric constants in the scaffold's rule sections, every rule constant appears (the 17 non-matches are the scaffold's worked-example values — `306078.71`, `4519664.50`, `95000.00`, `0.03`, `1250.80` etc. — plus comma-formatted or spelled-out equivalents such as `15,000` and "one thousand"). Two operator-syntax leaks (`>=`, `<=`) that had ridden in on scaffold endpoint descriptions in §4 were rewritten to prose; the file now contains zero comparison operators, zero pseudocode and zero fuzzy quantifiers.

**Hard Contract 3 — §3 Path Purity: PASS.** Every backticked token between `## 3.` and `## 4.` was extracted programmatically: **0** tokens start with `/`, **0** are a bare HTTP method, **0** are a method+path pair. §3 uses state-transition, role + gerund, and capability framing throughout. Paths appear only in §1/§2/§4, where they are permitted.

**Mandated completeness verification:** **82 / 82 endpoint paths** present as backticked table entries (table row count independently confirmed at 82, exactly 4 columns: Method, Path, Description, Authorized Role(s)); **50 / 50 error ids** present (row count 50, exactly 2 columns: Error ID, HTTP Status Code); **13 / 13 entities** present.

**Withheld files honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

**Six scaffold self-contradictions resolved** in favour of the reading with the most corroborating sources (recorded here so the implementer's tests can be reconciled if needed): `revision_round` increments on `UNDER_REVIEW -> RETURNED` and is read pre-increment for branch selection; cell construction dates use validation rung 3's "at or before" rather than the entity's "strictly after"; the special-waste window at clear-screening uses the logical clock per validation 16 rather than `operating_date`; survey restore on void orders by `flown_on DESC, created_at DESC`; `assurance_funded_amount` is set to `funded_amount`; and CQA resubmit is `SiteOperator`-only per the endpoint `roles` list.

**Orchestrator truncation check (per command guard):** independently verified — `wc -l` = 508, `tail -25` ends on the final error-catalogue table row, and `grep '^#'` shows all five top-level sections plus all ten §2 and all eleven §3 subsections present. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T14:42:00.000Z

Implementation complete.

## Modules written
All under `workspace/implementation/` (2748 lines of Python, 9 files):

| File | Lines | Contents |
|---|---|---|
| `core.py` | 473 | in-memory `Store` (dicts keyed by UUID), logical clock (epoch `2026-08-01T00:00:00Z`), `meta`/`response_type`/`data` envelope, all 50 error ids + HTTP codes, `X-User-ID`/`X-User-Role` auth + RBAC decorator (rungs 1-2), `limit`/`offset` pagination, `Decimal` `ROUND_HALF_UP` helpers, `Body` shape validator (rung 3) |
| `services.py` | 451 | 11 calculations, all aggregate recomputations (`sync_cell`/`sync_landfill`/`sync_approval`/`scheduled_gallons_today`), cascade helpers, site-scope check (rung 6) |
| `routes_site.py` | 253 | clock, landfills, posture steering, remaining-life projection, cell fork-join lifecycle |
| `routes_liner.py` | 278 | liner CQA cycle + depth-4 certification cascade, aerial surveys + void restore |
| `routes_ops.py` | 413 | operating days, day-close cascade, amend compensations, full waste-load dual-dimension lifecycle |
| `routes_env.py` | 352 | special-waste approvals, treatment agreements (lazy expiry), leachate shipments (half-open windows, slot + gallon gates, 5-step invoice) |
| `routes_gas.py` | 215 | gas wellfield (oxygen-critical refusal, two disjoint tune branches), surface-emission scans + 3-link exceedance cascade with the deterministic corrective-well selector |
| `routes_finance.py` | 262 | closure cost estimates (OCC, SoD certify, supersede, posture escalation, step-4-only fund-assurance), host community agreements (OCC execute, rung-9 amendment carve-out, amendment loop) |
| `app.py` | 51 | Flask app, route registration, `ApiError`/404/405/500 envelope handlers, `0.0.0.0:$PORT` |

Plus `start.sh` (executable, guarded `pip install`, `exec python3 app.py`) and `requirements.txt` (`flask`).

## Endpoint coverage
**82 / 82** — a programmatic diff of the registered Flask url_map against `SCAFFOLD.yaml`'s endpoint table reports `missing from impl: []` and `extra in impl: []`.

## Boot + smoke verification
Booted with `PORT=18719 bash start.sh`, exercised a full end-to-end chain, then killed by PID 1864103 (port confirmed closed; no broad `pkill` used). Verified live:
- envelope + `req_`-prefixed id, 401 unauth, 400 on `limit=0`, 404 unknown route, 405 wrong method
- landfill -> cell -> liner QA approve -> cell `QA_CERTIFIED`, landfill `certified_airspace_cy` 500000.0
- closure estimate: `closure_cost_total` **222601.86** (120001 sf x 1.855) and `post_closure_cost_total` **4519664.50** — the PRD's pinned round-each-then-sum figures exactly (not 4519664.49)
- OCC: second create with a stale `expected_landfill_version` -> `ERR_STALE_LANDFILL_VERSION` 412
- certify (SoD-clean officer) -> `CERTIFIED`, fund-assurance -> shortfall 0.0 / `FUNDED`; authorize -> `READY_FOR_WASTE`; activate -> `ACTIVE`
- gate pricing 1254.38; day close -> density 0.7066, consumption 30.99, load `FINALIZED` with royalty 57.49 and `final_charge_amount` 1278.42 while `gate_charge_amount` stayed 1254.38; life 1.6 yr -> landfill auto-`RESTRICTED_AIRSPACE`
- day amend -> day `AMENDED`, ledger back to 0.0, load back to `PROVISIONAL` with royalty/final nulled and gate charge preserved
- leachate: treatment_fee 928.00, tier 0.06, `invoice_total` 1248.68; derived `scheduled_gallons_today` 16000.0
- gas: `ERR_DUPLICATE_WELL_CODE` 409, `ERR_WELL_OXYGEN_CRITICAL` 422 at exactly 12.0, out-of-spec -> `TUNING_REQUIRED` + site `CORRECTIVE_ACTION`, in-spec -> `ONLINE` + site back to `COMPLIANT`; empty-pool exceedance still set `CORRECTIVE_ACTION` with `corrective_well_id` null
- HCA: `ERR_AMENDMENT_IN_PROGRESS` 409 on the rung-9 carve-out, execute-amendment -> `EXECUTED`

Storage is in-memory only; no seeding, no file/`/tmp` cache; `__pycache__` removed. Nothing written outside `workspace/implementation/`; never read `test_helpers/`, `test_suite/`, the two `SCAFFOLD_*_DESIGN.yaml` files, or any sibling task, and did not touch `worklog.md`.

## Step 5: Generate unit tests — 2026-09-04T15:44:00.000Z

Generation is complete. Both output directories sit at the task root; nothing under `workspace/` was created or modified.

**Files written**

`test_helpers/` (9 files): `__init__.py`, `types.py`, `api_errors.py` (50-id `ApiErrorId` enum + error->status map), `api_client.py` (one method per PRD endpoint), `constants.py`, `test_users.py` (all eight roles, entity-backed `SiteOperator`/`ScaleOperator` builders, header-omission variants), `factories.py`, `assertions.py`, `fixtures.py` (state-builders for every lifecycle).

`test_suite/`: `conftest.py` plus 17 test modules, **209 tests total**.

- Queue A (depth, `test_01`-`test_09`): 106 tests.
- Queue B (breadth, `test_10`-`test_17`): 103 tests — `test_10_entity_surface` (22), `test_11_state_machine_baselines` (20), `test_12_calculation_coverage` (5), `test_13_validation_rules` (7), `test_14_endpoint_surface` (7), `test_15_error_catalogue` (22), `test_16_access_control` (11), `test_17_concurrency_and_consistency` (9, written last: 4 for the closure-estimate OCC guard, 2 for the host-agreement OCC guard, 3 for the immediate QA-approval cascade).

**Instance coverage** — a whole-suite cross-check against both design indices reports `MISSING difficulty: []`, `MISSING corner: []`, `EXTRA tags: []`:
- Queue A: 28 of 28 difficulty instances translated.
- Queue B: 41 of 41 LIVE corner instances translated. The 31 `excluded_because` stubs were correctly not translated (each is redundant with a §1.8 instance, per its own rationale).
- No instance was skipped by the PRD-first filter; no test is untagged, dual-tagged, or points at a non-existent instance. Tag count equals `def test_` count in every file (209/209).

**Verification run**
- Every emitted `.py` in both directories: `python3 -m py_compile` clean, `python3 -m pyflakes` clean.
- All 209 `PRD: "..."` citations were machine-checked as whitespace-normalised substrings of `workspace/PRD.md`: 0 non-verbatim.
- `__pycache__` from the compile checks was removed.

**Design/PRD divergences resolved in favour of the PRD** (asserted the PRD outcome, test docstring notes the divergence): corner validations rung-21 refusal asserted on `POST /cells` rather than at begin-construction; corner #64's `'CONSTRUCTION'` asserted as `UNDER_CONSTRUCTION`; corner #59's `waste_stream: "CONSTRUCTION_DEBRIS"` mapped to the declared `CD`.

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk and could not have read it. Post-run layout check confirms `test_helpers/` and `test_suite/` are at the task root with no stray copies under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T16:20:00.000Z

All 8 rounds are green.

## Summary

**Iterations run:** 2 sweeps (initial diagnostic sweep + one confirming sweep after a single batch of fixes).

**Iteration 1 result:** every one of the 8 rounds reported an identical 125/209 (84 failing) — perfectly deterministic, so no load-induced flakiness to chase. Root-cause grouping of the 84 collapsed to just **two** defects, both in the test artifact plumbing (83 of 84 failures shared the exact same setup error `HTTP 401 ERR_UNAUTHENTICATED`).

**Tests deleted:** none. Every failure traced to a verbatim PRD rule; no PRD-silence or non-unique-derivability pattern was found.

**Fixes to `test_helpers/`:**
- `test_helpers/api_client.py` — `ApiClient.clear_screening`: signature was `(load_id, headers, payload=None)` while **all ten** call sites (in test_01/05/07/09/11/13 and `fixtures.clear_screening`) invoke it as `(load_id, None, headers)`; the header dict was being posted as the request body and the request went out unauthenticated. Changed the signature to `(load_id, payload, headers)` to match the body-taking convention used by every caller and by the sibling methods (`flag_waste_load`, `reject_waste_load`, `certify_weight`).
- `test_helpers/fixtures.py::certify_closure_estimate` — was calling `api_client.certify_closure_cost_estimate(estimate_id, None, headers or FINANCE_CERTIFIER)` against the `(estimate_id, headers, payload=None)` signature, so the `FinanceOfficer` certifier headers landed in the payload slot and every certification 401'd. This single line is what broke `setup_funded_assurance` -> `setup_ready_for_waste_cell` -> `setup_active_site`, cascading into 83 tests across 15 files. Fixed to `(estimate_id, headers or FINANCE_CERTIFIER)`.
- `test_helpers/fixtures.py::close_operating_day` — same argument-order slip on `close_operating_day(day_id, None, headers)`; fixed to `(day_id, headers)`, matching the three call sites in test_15.

**Fixes to `test_suite/`:**
- `test_07_cross_entity_state_dependencies.py:496` — `close_operating_day(day_id, None, headers)` -> `(day_id, headers)` (same argument-order slip).
- `test_16_access_control.py:375` (`test_the_bar_also_covers_returning_and_approving_the_package`) — the return payload used `{"review_comment": ...}`, but PRD §3.2 states verbatim "A `CqaEngineer` supplies a `return_note`." The malformed body tripped rung 3 (`ERR_INVALID_REQUEST`, 400) before rung 12 could report the segregation-of-duties refusal the test asserts. Corrected the field to `return_note`, which makes the test faithful to PRD rather than weakening it — the exact `ERR_SEGREGATION_OF_DUTIES`/403 assertion is untouched.

**Fixes to `implementation/`:** none. No implementation defect survived diagnosis; the impl was already correct on all 84 failures.

**Final sweep evidence** (`workspace/implementation/results.1..8.json`, per-round server reboot isolation):

| round | passed | total | failed | errors |
|---|---|---|---|---|
| 1 | 209 | 209 | 0 | 0 |
| 2 | 209 | 209 | 0 | 0 |
| 3 | 209 | 209 | 0 | 0 |
| 4 | 209 | 209 | 0 | 0 |
| 5 | 209 | 209 | 0 | 0 |
| 6 | 209 | 209 | 0 | 0 |
| 7 | 209 | 209 | 0 | 0 |
| 8 | 209 | 209 | 0 | 0 |

Note for the orchestrator: the whole 84-test failure block was one class of bug — `test_helpers/api_client.py` mixes two positional conventions for action endpoints (`(id, payload, headers)` for body-taking, `(id, headers, payload=None)` for body-less), and the fixture/test authors used the two interchangeably. It is worth a static consistency check on generated `api_client.py` files, since the failure mode (a 401 from a header dict posted as the body) looks exactly like an auth bug in the implementation.

**Orchestrator verification (per Step 7 artifact-check policy):** independently re-read all 8 `results.$i.json` off disk (all present, ~63.6 KB each, mtime 16:19). Confirmed `passed=209 total=209 failed=0 errors=0` for every round. The green claim is backed by real artifacts.

**Step 8 decision:** Step 7 applied **0 fixes to `implementation/`**, but it was NOT a zero-iteration exit — it ran 2 sweeps and applied 3 `test_helpers/` fixes plus 2 `test_suite/` fixes. The skill's skip condition requires 0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes, so the skip condition is not met and Step 8 will run. Its `<step_7_diff>` focus list is dominated by fixture argument-order slips (pure test plumbing bugs, not PRD silences), with one genuine PRD-relevant item: the `return_note` vs `review_comment` field name on CQA package return. Step 8 is expected to make few or no PRD edits; that is the correct outcome for a diff of this shape and is not a failure of the step.

## Step 8: Finalize PRD — 2026-09-04T16:23:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created as a byte-identical copy of `workspace/PRD.md`. **Zero PRD edits** — no item in `<step_7_diff>` revealed PRD-silence or PRD/impl mismatch.

- **Line counts:** PRD.md 508 -> PRD_FINALIZED.md 508 (**0.00% delta**, `diff` reports IDENTICAL).
- **Change list:** none.

## Per-item analysis (why no edit)

**Items 1-4 — argument-order slips in `test_helpers/api_client.py::clear_screening`, `test_helpers/fixtures.py::certify_closure_estimate`, `test_helpers/fixtures.py::close_operating_day`, `test_suite/test_07:496`.**
Subject: header/payload positional-argument convention in the test client. Impl paths enumerated: `implementation/core.py:346-365` (`endpoint` wrapper — rung 1 reads `X-User-ID`/`X-User-Role`, raises `ERR_UNAUTHENTICATED` when either is absent), `implementation/routes_ops.py:298` (`clear-screening` handler — no `Body()` at all), `routes_ops.py:89` (`/operating-days/{id}/close` — no `Body()`), `routes_finance.py:75-88` (`/certify` — no `Body()`), plus `core.py:369-383` (`Body.__init__` tolerates an absent body and ignores unknown keys). All four failures were a client bug: the header dict landed in the payload slot, so the request went out with `headers=None` and correctly 401'd per PRD §2.1 ("If either header is absent ... `ERR_UNAUTHENTICATED` (401) ... before anything else"). The behavior the tests hit is verbatim PRD; the endpoints take no body, which PRD already states for close ("carries no body at all", §3.6) and leaves unremarkable for `clear-screening`/`certify` since impl requires nothing there. No PRD wording is under-determined by these fixes -> no edit.

**Item 5 — `test_16_access_control.py:375`, `review_comment` -> `return_note`.**
Subject: the return-for-rework request field and the ladder position of shape validation vs. segregation of duties. Impl paths enumerated: `routes_liner.py:86-109` (`return_package`: `Body()` then `b.string("return_note")` at line 88, *then* `get_or_404`, *then* the `UNDER_REVIEW` state check, *then* the `submitted_by_user_id` segregation check), `core.py:404-415` + `core.py:389-395` (`string()` defaults to `required=True`; a missing/null field is `ERR_INVALID_REQUEST` 400), and the sibling note-bearing handlers for consistency (`routes_liner.py:151` `certification_reference`, `routes_liner.py:259` `void_reason`, `routes_ops.py` amend/flag/reject reasons, `routes_env.py`/`routes_gas.py` decision/offline/remediation reasons) — all use the same required-string convention that PRD expresses uniformly as "supplies a `<field>`". PRD §3.3 line 201 already names `return_note` verbatim, and §2.9 already pins rung 3 (body shape) ahead of rung 4 (path ids) and rung 12 (segregation), which is exactly the impl order. The test was simply unfaithful to a rule PRD already fixes; the corrected test still asserts `ERR_SEGREGATION_OF_DUTIES`/403 -> no edit.

No edits were committed, so there is no wording-adjustment log; the mandatory subject/path enumeration for each candidate edit is recorded above.

**Orchestrator note:** a byte-identical `PRD_FINALIZED.md` is the expected and legitimate outcome here, because Step 7 applied **zero** `implementation/` fixes — the entire 84-test failure block was test-plumbing argument-order slips. Step 8's mandate is to patch PRD only where impl pinned a choice PRD left open; with no impl change and no impl/PRD divergence surfaced, there is nothing in scope to patch. Verified with `diff -q` (identical). Step 9's full impl scan, which does not depend on the Step 7 diff, is where residual silences will be closed — and Step 9 must NOT come out identical.

## Step 9: Complete PRD — 2026-09-04T16:52:00.000Z

**Orchestrator execution note.** Step 9 was run as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md`, rather than as a single subagent. A single pass over 2,748 lines of implementation plus a 508-line / 115 KB PRD reliably under-scans and can even come back byte-identical, which is the one outcome Step 9 must never produce. Partition: pass 1 owned `core.py` + `services.py` + `app.py` (cross-cutting envelope/clock/errors/RBAC/pagination/rounding + all 11 calculations + all aggregate recomputations) and performed the `cp` from `PRD_FINALIZED.md`; pass 2 owned `routes_site.py` + `routes_liner.py` + `routes_ops.py`; pass 3 owned `routes_env.py` + `routes_gas.py` + `routes_finance.py` and additionally carried the final-pass file-integrity duty. Passes 2 and 3 were explicitly forbidden from re-copying the file and were handed the prior passes' pinned findings so they neither redid nor contradicted them.

### Pass 1 — core.py / services.py / app.py

508 lines before -> 508 after (all in-paragraph). **11 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 — revise — ambiguity — an empty-string `X-User-ID`/`X-User-Role` is treated as absent (401) — `core.py:354`
- §2.2 — revise — ambiguity — `api_request_id` pinned to `req_` + exactly 20 upper-case-alphanumeric chars — `core.py:270`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the host's real UTC clock, not the logical clock — `core.py:271,102`
- §2.3 — revise — ambiguity — a non-base-10-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `core.py:301-317`
- §2.3 — revise — ambiguity — `created_at` ties broken by creation sequence, across all listings, none overriding — `core.py:243,326-331`
- §2.3 — insert — ambiguity — filter compares supplied text to the stored value rendered as a string; null fields never match; undeclared query params ignored — `core.py:334-342`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` stamped from host real UTC time — `core.py:225-226`
- §2.4 — revise — **mismatch** — epoch renders `2026-08-01T00:00:00.000Z`; client ISO instants canonicalised to 3-digit-ms `Z` with offsets converted to UTC — `core.py:92,455-463`
- §2.9 rung 3 — insert — ambiguity — absent/blank body read as `{}`; non-object body fails; undeclared fields ignored; explicit-null optional field takes its default; required strings accept any length — `core.py:373-415`
- §3.3 — insert — ambiguity — "rounded up" is a true ceiling (1,000 ft -> 2 samples) — `services.py:140`
- §3.7 — insert — ambiguity — creation sequence breaks a remaining royalty-waterfall tie — `services.py:414-416`
- §3.9 — insert — ambiguity — `measured_remaining_airspace_cy` reported verbatim, never re-rounded — `services.py:190-191`
- §3.9 — revise — **mismatch** — `remaining_life_years` is also refreshed on cell activation and closure — `services.py:319`
- §3.10 — insert — **mismatch** — `scheduled_gallons_today` is recomputed from the clock-date definition — `services.py:353-360`
- §4 — revise — **mismatch** — leachate sub-resource listing "in window order" -> "in creation order" — `core.py:326-331`
- §5 intro — insert — ambiguity — unrouted path -> `ERR_NOT_FOUND`/404, disallowed method -> `ERR_NOT_FOUND`/405, unexpected failure -> `ERR_INVALID_REQUEST`/500 — `app.py:33-46`

Verified already uniquely pinned: full error-id->status map; all envelope shapes incl. `has_more`; pagination defaults/bounds; `version`/`touch()`; rungs 1-2 and 6; round-half-up precision policy; all 11 calculations and every pinned rounding order; all aggregate recomputations; all cascade helpers; all domain constants.

### Pass 2 — routes_site.py / routes_liner.py / routes_ops.py

508 lines before -> 508 after. **13 ambiguity-pins, 16 mismatch-revisions** (29 edits; line 134 edited twice).

- §2.3 — revise — mismatch — "four sub-resource listings" -> "five" — `routes_ops.py:84`
- §2.4 — insert — ambiguity — clock endpoint answers a `data` object carrying only `current_utc` — `routes_site.py:15`
- §2.7 — insert — ambiguity — all six "site not CLOSED" preconditions refuse with `ERR_INVALID_STATE_TRANSITION`, after the addressed resource's own state — `routes_site.py:179/201/222`
- §2.9 rung 3 — insert — mismatch — endpoints declaring no input field never parse the body, so malformed JSON is ignored — `routes_site.py:172/215`
- §2.9 rung 3 — revise — mismatch — added `coverage_period_end <= flown_on` to the cross-field list — `routes_liner.py:201`
- §2.9 rung 7 — revise — mismatch — removed `POST /liner-qa-packages` (yields `ERR_SITE_SCOPE_VIOLATION`), added `POST /operating-days` — `routes_liner.py:25`, `routes_ops.py:43/243`
- §2.9 rung 10 — revise — mismatch — also guards `POST /operating-days`, where only sub-check (b) runs — `routes_ops.py:46`
- §2.9 rung 27 — revise — mismatch — `ERR_FINANCIAL_ASSURANCE_SHORTFALL` also arises on `POST /landfills/{id}/operating-status` — `routes_site.py:79/207`
- §3.1 — insert — ambiguity — posture enum accepts all five; three non-move targets parse then fail `ERR_INVALID_STATE_TRANSITION` — `routes_site.py:69/96`
- §3.1 — revise — mismatch — a `CLOSED` site still accepts a new cell row; refusal falls on `begin-construction` — `routes_site.py:114/179`
- §3.3 — revise — mismatch — liner-package cross-site refusal is `ERR_SITE_SCOPE_VIOLATION` — `routes_liner.py:25`
- §3.3 — insert — ambiguity — `return_note` validated but never persisted — `routes_liner.py:88`
- §3.4 — insert — ambiguity — `approval_reference` validated but never persisted — `routes_site.py:195`
- §3.5 — insert — ambiguity — `special_waste_approval_id` on MSW/CD -> `ERR_INVALID_REQUEST`; explicit null counts as omission — `routes_ops.py:235`
- §3.5 — insert — ambiguity — day must still be `OPEN` at receipt, checked ahead of site and cell gating — `routes_ops.py:253`
- §3.5 — insert — ambiguity — on reject the approval's `version` moves only when the recomputation moves the figure — `routes_ops.py:396`
- §3.5 — insert — ambiguity — certify-weight's only precondition is `CLEARED`; day state never read; weight may be overwritten post-close with no re-pricing — `routes_ops.py:408`
- §3.6 — revise — mismatch — `operating_date` stored as a canonicalised instant, never truncated; `ERR_CROSS_SITE_REFERENCE`/`ERR_CELL_NOT_ACCEPTING_WASTE` named; site posture never consulted; uniqueness compares the whole instant — `routes_ops.py:37/44/47/51`
- §3.6 — revise — ambiguity — the five close preconditions evaluate in §2.9 ladder order, not narration order — `routes_ops.py:104-123`
- §3.6 — revise — mismatch — landfill `version` +1 exactly over the whole close whether or not link 3 fired; tonnage sync covers approvals referenced by any load — `routes_ops.py:160/162-169`
- §3.6 — revise — ambiguity — amend recomputes approvals referenced by any load and cannot lift `RESTRICTED_AIRSPACE` (only `SUSPENDED_NO_AIRSPACE`) — `routes_ops.py:209-220`
- §3.9 — insert — ambiguity — void-restore tie-break: later-created row wins a tie surviving `flown_on` then `created_at` — `routes_liner.py:271`
- §3.9 — insert — ambiguity — the automatic `OPEN -> RESTRICTED_AIRSPACE` move happens on exactly two occasions (day close, survey record) — `routes_liner.py:242`, `routes_ops.py:159`
- §4 — revise — mismatch — operating-status row now lists the real source-state sets — `routes_site.py:73`
- §4 — revise — mismatch — cell liner packages listed "in creation order", not "revision order" — `routes_liner.py:66`
- §4 — revise — mismatch — resubmit no longer claims it increments `revision_round` — `routes_liner.py:132-141`
- §4 — revise — mismatch — void restores the SUPERSEDED survey with the latest `flown_on` — `routes_liner.py:270`
- §4 — revise — mismatch — clear-screening runs from "PENDING or FLAGGED" — `routes_ops.py:311`
- §4 — revise — mismatch — reject runs from "PENDING or FLAGGED" and voids the billing dimension — `routes_ops.py:381/389`

Verified already uniquely pinned: landfill registration field set/bounds/defaults; the four landfill derivations and certified-cell state set; remaining-life-projection response; cell creation and `fill_pct`; piggyback rules and rung 7->20->21 order; conformance score and clamps; one-package-in-flight; begin-review/approve SoD and the 85.0 threshold with equality passing; the return branch's read-before-modify on `revision_round`; the depth-4 approval cascade; authorize/activate/close-cell; survey overlap-as-closed-intervals and 90-day spacing; the day-close four steps and four cascade links; the five amend compensations; waste-load receipt and the nine clear-screening checks in ladder order.

### Pass 3 — routes_env.py / routes_gas.py / routes_finance.py (+ final integrity duty)

508 lines before -> 508 after. **13 ambiguity-pins, 4 mismatch-revisions.**

- §2.9 rung 7 — revise — mismatch — rung applies only to `POST /waste-loads`, `POST /operating-days`, `POST /cells`; removed `POST /gas-wells`, `.../connect`, `POST /leachate-shipments`, `POST /surface-emission-scans` (each resolves a single FK and raises no `ERR_CROSS_SITE_REFERENCE`); dropped two now-false clauses. Grep confirms `ERR_CROSS_SITE_REFERENCE` is raised only in `routes_ops.py:44,244,248,251` and `routes_site.py:133`. **This resolves the hand-off pass 2 flagged.**
- §2.9 rung 3 — insert — ambiguity — every narrative reason/note/reference field with no stated length bounds is required and non-null (verified: no `required=False` narrative field anywhere) — `routes_env.py:96,188,289,322`
- §3.5 — insert — ambiguity — requesting a profile never consults site posture and leaves the landfill untouched — `routes_env.py:51-77`
- §3.7 — insert — ambiguity — neither amendment call nor drafting touches the landfill row; only execute and terminate do — `routes_finance.py:209-247,148-164`
- §3.8 — insert — ambiguity — the filing officer's id is retained privately for SoD and is not client-visible — `routes_finance.py:56`
- §3.8 — insert — ambiguity — `fund-assurance` consults no lifecycle state and leaves `status` unchanged — `routes_finance.py:112-128`
- §3.10 — revise — mismatch — `daily_gallon_cap` is a whole number >= 1 (a fractional cap fails rung 3) — `routes_env.py:144`
- §3.10 — revise — mismatch — expiry has two producer paths (booking, single read); reinstatement past `expires_on` refuses with `ERR_INVALID_STATE_TRANSITION` without expiring the row; `effective_from` gates nothing — `routes_env.py:21-28,170-211`
- §3.10 — insert — ambiguity — every agreement representation reports a freshly derived `scheduled_gallons_today`; refreshing on a read never bumps `version` — `routes_env.py:31-35,177-182`
- §3.10 — insert — ambiguity — neither window instant is compared to the logical clock; site `operating_status` never consulted on any shipment move — `routes_env.py:223-255`
- §3.10 — insert — ambiguity — agreement-side `version` bump is unconditional on book/cancel/reject-at-gate; dispatch and confirm-acceptance leave the agreement alone — `routes_env.py:269-270,332-333,350-351`
- §3.11 — revise — mismatch — drilling a well raises no `ERR_CROSS_SITE_REFERENCE` and does not consult the cell's development state — `routes_gas.py:22-44`
- §3.11 — insert — ambiguity — the three wellhead readings carry no bounds of their own — `routes_gas.py:82-84`
- §3.11 — insert — ambiguity — in-spec tune leaves an already-`COMPLIANT` landfill untouched — `routes_gas.py:103-105`
- §3.11 — insert — ambiguity — take-offline bumps the landfill only when `gas_collection_status` actually moves — `routes_gas.py:123-125`
- §3.11 — insert — ambiguity — `exceedance_point_ref` non-empty, no upper bound; explicit null read as absent on both sides of the threshold — `routes_gas.py:150-156`
- §3.11 — insert — ambiguity — the corrective-well selector's final tie-break is creation sequence, earlier-created well winning — `routes_gas.py:15-17`

Verified already uniquely pinned: the five-step leachate invoice and tier boundaries; slot gate as an aggregate count including the new shipment, half-open overlap, gate order (expiry -> slot -> gallons); shipment lifecycle; approval approve/deny/revoke; the two disjoint tune branches with inclusive spec bounds and the oxygen-critical refusal ordered after the well's own state; connect/abandon preconditions; the 3-link exceedance cascade incl. link 3 on an empty candidate pool; the four-step closure cost model and its two summation orders; certify's DRAFT -> CLOSED-site -> SoD ordering, the `SUPERSEDED` sweep and the second-consecutive-shortfall escalation to `LAPSED` + `SUSPENDED_FINANCIAL`; HCA execute's concurrency-before-own-state order and the supersede sweep; the rung-9 carve-out; execute-amendment's exactly-five overwritten fee fields.

### Step 9 totals and integrity

**37 ambiguity-pins + 24 mismatch-revisions = 61 edits** across the three passes, all in-paragraph; no new sections, no new paragraphs, line count unchanged at 508.

Pass 3's final-pass integrity check, independently re-verified by the orchestrator: 5 top-level sections (§1-§5), 10 §2 subsections + 11 §3 subsections = 21, §4 endpoint table **82 rows**, §5 error table **50 rows**, file ends at a real boundary (final `ERR_FINANCIAL_ASSURANCE_SHORTFALL | 402` row). `diff PRD_FINALIZED.md PRD_COMPLETED.md` = **108 changed lines** — emphatically NOT byte-identical, so the scan demonstrably ran. Size grew 115,350 -> 128,444 bytes (+13,094, +11.4%) while staying at 508 lines, which is the signature of pure in-paragraph pinning.

**Green-state preservation.** Steps 8 and 9 were forbidden from writing `implementation/`, `test_suite/`, or `test_helpers/`. Verified by mtime: every implementation file (14:11-14:28) and every test file (latest 16:08) predates the passing sweep's `results.*.json` (16:19), and no file in either tree has been touched since. The 8/8 x 209/209 result therefore still describes the artifact as it stands. Removed the `__pycache__` trees and `.pyc` files left behind by the test runs, and the spliced `sweep.log`, so the delivered task directory contains only real artifacts.

**PIPELINE COMPLETE** — `workspace/PRD_COMPLETED.md` written; all nine steps done.
