# Worklog — task_2430_unscripted_casting_participant_agreements

## Step 1: Create task directory — 2026-09-02T16:09:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements` and its `workspace/` subdirectory. Index 2430 was fixed by the scenario number; no auto-allocation scan was performed (concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-02T18:11:00.000Z

All three artifacts are complete and the lint is clean.

## Files written to `/home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements/`

- `SCAFFOLD.yaml` (2636 lines) — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2122 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (6223 lines) — single top-level key `scaffold_corner_design`

## §1.0–§1.7 counts

13 entities (flat topology) · 48 endpoints · 9 state machines / 38 transitions (cyclic) · 11 calculations · 46 ordered validations · 53 errors · 2 concurrency rules · 6 roles (segregation_of_duties) · `difficulty_level: expert_plus` · layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, ops_run_checkpoint]` · `consistency_model: immediate` · `api_prefix: /casting`

## §1.8 — 22 instances (all 9 rules, ≥2 each)

dual_variant_calc 2 · combinatorial_formula 3 · non_linear_state_machine 3 · transitive_cascade 2 (depth 4 and depth 5) · priority_pair_validation_conflict 2 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 3 · compensating_invariant 2

## §1.9 — 75 active instances + 20 stubs, over all 9 sections

entities 12+0 · state_machines 12+6 · calculations 10+3 · validations 14+1 · endpoints 5+0 · errors 12+7 · rbac 5+0 · cross_cutting_complexity_layers 4+3 · consistency_model 1+0

Every stub's `excluded_because.difficulty_instance` resolves to an existing `rule_id / name` pair in the difficulty file (verified programmatically), and all 97 instance names are unique across the union of both design files.

## Design adjudications (recorded in the corner file's header)

1. `entities / parent_relationships` — skipped: `entity_topology: flat`, every §1.1 row declares `parent: null`; the FK claim is instead carried by `foreign_key_references`.
2. Cross-cutting layer `ops_run_checkpoint` — the claim-extraction guide declares no row of that name, so the welfare-run epoch checkpoint is filed under the nearest declared row, `cross_cutting_complexity_layers / scheduled_actions` (an active instance proving the sweep is explicitly triggered, never a background timer, and is scoped to the addressed production). No claim_type was invented.

Two additional judgement calls made while authoring: `cascading_side_effects` carries both an active instance (a rejected execute leaves no partial cascade — the negative direction) and a stub pointing at the depth-5 escalation cascade (the positive direction); and the errors section deliberately proves priority shadowing rather than isolated error ids where the ladder makes the specific error unreachable (e.g. priority 25 shadows 26 at send, priority 10 shadows 13 on counter-offer, priority 9 precedes 35 on agreement create).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  1210

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two lint/parse defects were found and fixed on the way to clean: bracketed list JSONPaths (`$.data[0].status`) had to be quoted inside YAML flow mappings, and `provisional_risk_score` was being captured off a `ScreeningItem` response (moved to the `GET /casting/applicants/{id}` read, where the field is declared). The hard constraint was honoured — no sibling `task_*/` directory was listed, globbed, grepped, or read at any point.

## Step 3: Copy Shared Files — 2026-09-02T18:12:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:24:00.000Z

PRD generated and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements/workspace/PRD.md`
**Line count: 424** (file ends with a newline at line 425).

### Section list
- §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Resource Identity, Audit Fields and Record Versioning; 2.5 The Logical Production Clock; 2.6 Request Admission Order; 2.7 Casting Posture: the Production-Level Gate; 2.8 Arithmetic, Rounding and Comparison Conventions; 2.9 Optimistic Concurrency Control; 2.10 Segregation of Duties; 2.11 Conserved Quantities and Compensating Actions; 2.12 Jurisdictional Minimums for Minor Participants
- §3 Business Logic & Workflows — 3.1 Standing Up a Production and Its Venues; 3.2 Distributing Casting Calls and Open-Call Logistics; 3.3 Applicant Intake, Eligibility and Withdrawal; 3.4 Screening Instruments, Risk Scoring and Medical Clearance; 3.5 Minor Participant Protections and the Blocked Trust; 3.6 Drafting, Negotiating and Executing Participant Agreements; 3.7 Welfare Protocols, Duty of Care and the Welfare Epoch; 3.8 Shooting Blocks, Incidental Releases and Minor Hour Caps; 3.9 Post-Production Obligations, Complaints and Aftercare
- §4 Endpoint Definitions (48 rows, 4 columns)
- §5 Error Code Catalogue (53 rows, 2 columns) — **last section**

### Coverage audit (documented vs declared)
- Endpoints: 48 / 48 in §4 table (verified by row count against scaffold)
- Entities: 13 / 13; entity field names 117 / 117 present in backticks
- Request-body identifiers: 76 / 76; query/path params: 17 / 17
- Validations: 46 / 46 rendered as the ordered admission ladder in §2.6 (priority order preserved 1→46, each with its `error_id`, HTTP status and full `applies_to` scope)
- Errors: 53 / 53 in §5 table, and all 53 IDs also appear in §2/§3 prose (no error mentioned only in the table)
- State machines: 9 machines / 38 transitions, all `from`→`to` pairs, preconditions and side-effect cascades expressed (including the 5-link withdraw cascade, 4-link execute cascade, 5-link complaint-escalation cascade, and both posture cascades)
- Calculations: 11 / 11 with all constants embedded in business prose and both dual variants (`PROVISIONAL`/`FINAL` stipend, `PROVISIONAL_CEILING`/`FINAL_DECAYED` risk) given equal density
- Concurrency rules: 2 / 2 (`expected_applicant_version`→`ERR_STALE_APPLICANT_VERSION` 412; `expected_agreement_version`→`ERR_STALE_AGREEMENT_VERSION` 412)
- Roles: 6 / 6 with `identity` translated (five `opaque`, `Applicant` entity-backed)

### Hard Contract reports
```
Field coverage check:
- entities[].fields: 117 required, 117 present, 0 missing
- endpoints[].request_body: 76 required, 76 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 46 checked, 46 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + status all named), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 46 checked, 46 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 48 checked, 48 expressed, 0 missing
- entities[].fields[] structured content: 117 checked, 117 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (send from DRAFTED/REVISED, manual vs superseded void, aftercare vs escalation route, RESTRICTED vs FROZEN posture cascade, both stipend variants, both risk variants), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 733
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§2.2 was verified byte-identical to `section-2.2-response-structure.md`. No fuzzy/approximating words present (the only "around" hit is inside `turnaround_buffer_minutes`).

### Verbatim tail confirmation
The last 60 lines were read: the file terminates at the complete §5 Error Code Catalogue table, final line `| \`ERR_WELFARE_BUDGET_EXCEEDED\` | 409 |` — a genuine section boundary, not mid-sentence or mid-table. No audit footer was written into the PRD.

**Orchestrator anti-truncation verification (independent):** `wc -l` = 424; §5 error table contains exactly 53 `ERR_` rows; §4 endpoint table contains 50 pipe-rows (48 endpoints + header + separator); last line is a complete table row at a genuine section boundary. Grep for the difficulty instruction string in PRD.md returns 0 hits — no leakage. PRD accepted; no regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-02T20:03:00.000Z

Complete. The full PRD-compliance suite for task_2430 is on disk and verified.

## Files written

**`test_helpers/` (10 files)** — `__init__.py`, `api_client.py` (`/casting` prefix, `ApiClient(GenericApiClient)`), `api_errors.py` (`ApiErrorId`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`test_suite/` (19 files)** — `conftest.py` plus:

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty, §1.8) | `test_01`…`test_09` | **44** |
| B (Corner, §1.9) | `test_10`…`test_18` | **75** |

Queue B breakdown: `test_10_entity_contracts` 12, `test_11_state_machine_contracts` 12, `test_12_calculation_contracts` 10, `test_13_validation_contracts` 14, `test_14_endpoint_contracts` 5, `test_15_error_contracts` 12, `test_16_rbac_contracts` 5, `test_17_cross_cutting_contracts` 4, `test_18_consistency_contracts` 1.

**Total 119 tests**, all collected by pytest with zero errors.

## Design-index coverage

- Difficulty: 22 live instances (0 stubs) → 44 tests, exactly 2 per instance.
- Corner: 75 live instances + 20 `excluded_because:` stubs → 75 tests, exactly 1 per live instance; **no stub translated**.
- Machine-checked: every test docstring ends with exactly one `Design:` line; no untagged, dual-tagged, dangling or stub-pointing tags; 97/97 live instances covered.

## Skipped instances

**None.** Every live instance in both indices passed the PRD-first two-condition filter, so nothing was dropped for PRD-silence or non-unique-derivability.

## Where recipes contradicted the PRD, the PRD won (assertions narrowed, never weakened elsewhere)

- Complaint opening status asserted `OPEN` (PRD §3.9 line 299), not the recipe's `SUBMITTED`.
- Trust-deposit test asserts the production's `trust_escrow_balance_cents == 0` before funding (PRD §3.1) instead of the packet's unspecified opening deposit field, and drops the unspecified `installment_count` echo.
- Enhanced-support test advances the logical clock one day per screening item so the decay ordering rests on `recorded_at` rather than an unreliable `created_at` tie-break (scores unchanged: provisional 12.75, final 9.83).
- `logical_clock_default` test omits `created_at`-equals-clock assertions (PRD §2.5 ties only deadlines/expiries/windows/ages to the clock).
- `MEDICAL_STANDBY` recipe uses were replaced with real `WelfareProtocol.kind` members (PRD §3.7 line 269) with arithmetic preserved.
- Post-obligation ordering asserted by `(kind, sequence_ordinal)` lookup rather than list position, since PRD §3.9 pins creation order, not list order.

## Citation audit

A verbatim grep pass against `workspace/PRD.md` found and fixed 7 truncated quotes (prefix-cut sentences in `test_04`, `test_10`, `test_15`, and one fabricated sentence "The tier opens at `STANDARD`." in `test_16`, replaced with the real §3.7 tier sentence). All docstring quotes now match the PRD verbatim; no comment or docstring anywhere mentions "scaffold". `pyflakes` is clean on `test_suite/` (the only warnings are the intentional re-exports in `test_helpers/__init__.py`).

Nothing under `workspace/implementation/` was read or written.

## Step 6: Generate Implementation — 2026-09-02T19:02:00.000Z

Implementation complete and verified.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2430_unscripted_casting_participant_agreements/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | `set -euo pipefail`, `cd $(dirname $0)`, pip install only if `import flask` fails, `exec python3 app.py` on `$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 76 | app factory, 5 blueprints, `before_request` lock + `g.touched`, ApiError/HTTPException/Exception handlers |
| `clock.py` | 70 | logical clock singleton, default exactly `2026-08-01T00:00:00Z`, ISO parse/format (3 fractional digits + `Z`), `real_now_iso()` |
| `errors.py` | 128 | `ApiError`, status map for all 53 catalog ids + 404/405/500, default messages |
| `envelope.py` | 61 | `meta` builder (`req_` + 20 uppercase alnum, real wall-clock stamp), object/list/error responses, `has_more` |
| `store.py` | 90 | 13 in-memory dicts, `RLock`, `new_record`, `touch` (dedup), `serialize` (drops `_`-prefixed), `by_seq` |
| `validation.py` | 256 | rungs 1–4 auth/ownership, typed field helpers, pagination (rung 8) |
| `calc.py` | 232 | all 11 calculations as pure Decimal/ROUND_HALF_UP functions + pinned constants |
| `services.py` | 606 | domain layer: 404 getters, parent/child walkers, rollup re-summation, posture derivation + cascades, screening/medical dimensions, packet derivation, obligation generation, void unwind, release coverage, 5-step welfare sweep |
| `routes_production.py` | 240 | productions, welfare-run, welfare protocols, locations, `/_clock/set_current_utc` |
| `routes_casting.py` | 550 | casting calls, applicants, screening items, minor protections, trust deposits |
| `routes_agreements.py` | 567 | agreements + negotiation, post-obligations, complaints |
| `routes_blocks.py` | 321 | shoot blocks + releases |

Total 3,208 lines. No `__pycache__`, no data files; storage is in-memory dicts only, all 13 collections empty on every boot, nothing seeded.

## Endpoint coverage: 48 / 48
Machine-verified by diffing `SCAFFOLD.yaml`'s `(method, path)` pairs against Flask's `url_map`: **declared 48, missing 0, extra 0** (only Flask's `/static`). Note there is deliberately no `GET /casting/productions` list route — it is not declared, so it correctly returns `ERR_METHOD_NOT_ALLOWED` 405.

## Architecture
- **Validation ladder** — the 46-rung PRD §2.6 order is encoded as explicit statement order in each handler: rungs 1–3 in `authenticate()`, rung 4 ownership (path-id compare for applicants; after 404-load for agreements/complaints so 404 precedes 403), rung 6 body-FK existence *before* rung 7 shape, then rungs 9/10 OCC, 11/12 posture, 13/14 state, then endpoint-specific rungs. Pinned interleavings: shoot-block schedule 26→39→40→41→42; roll 28→29→30; protocol plan shape→38→45; activate state→38→coverage→45.
- **State machines** — 9 machines as guarded transitions. Applicant carries two independent dimensions (`screening_status` × `medical_status`) recomputed from its screening items; agreement negotiation is cyclic (`SENT→COUNTERED→REVISED→SENT`) with `round_number` incremented by a shared `_append_round` writing unversioned NegotiationRounds; complaints fork-join into AFTERCARE (no production mutation) vs ESCALATED (breach on WELFARE/HARASSMENT with severity >= 4).
- **Calculations** — all Decimal + ROUND_HALF_UP in `calc.py`, with the three pinned rounding orders: per-component rounding before summation for stipend, round-per-installment-then-multiply for trust, round sessions before the 24 cap for aftercare. Conserved quantities (`stipend_committed_cents`, `welfare_committed_cents`, `trust_escrow_balance_cents`, `minor_participant_count`, `breached_obligation_count`, `welfare_incident_count`) are always full re-summations, never deltas. Posture is derived FROZEN > RESTRICTED > OPEN with integer cross-multiplication, and cascades fire only on change.
- **OCC** — `expected_applicant_version` on draft → `ERR_STALE_APPLICANT_VERSION` 412; `expected_agreement_version` on counter-offer → `ERR_STALE_AGREEMENT_VERSION` 412. `version`/`updated_at` move at most once per record per request via request-scoped `g.touched`; a request-wide `RLock` serialises all mutations.
- **Clock** — every entity stamp uses the logical clock (never wall-clock fallback); only `meta.api_request_timestamp` uses real time. Setting the clock mutates nothing and fires no sweep.

## Boot confirmation
`PORT=18431 bash start.sh` on a fresh process: Flask logged `Running on http://127.0.0.1:18431`, then
- `GET /casting/casting-calls` → 200 with `data: []`, `meta.total_count 0`, `has_more false` (clean empty store)
- `POST /casting/productions` → 201 with `duty_of_care_tier ENHANCED`, `casting_posture OPEN`, all rollups 0, `created_at 2026-08-01T00:00:00.000Z`, `version 1`
- missing/unknown auth headers → 401 `ERR_UNAUTHENTICATED`; bad enum → 400 `ERR_INVALID_REQUEST`

Two smoke scripts pass end to end, covering the adult path (publish -> intake -> 4 screening items -> draft -> send -> counter -> revise -> resend -> execute -> obligations -> fulfill -> welfare protocol -> shoot block roll/release/wrap -> complaint triage/route ESCALATION/resolve -> clock jump -> welfare-run breaching 2 overdue obligations -> void unwind) and the minor path (education-hours shortfall, trust-deposit shortfall, packet COMPLETE, risk 4.25 provisional / 2.88 final, stale applicant version, send with provisional stipend 700000, execute with total commitment 211200, minor cap 1 -> posture RESTRICTED with only OPEN_CALL calls suspended, trust per-installment 10560 x 3 = 31680, and a withdraw cascade conserving back to zero).

Housekeeping done: background servers stopped, `__pycache__` removed. The hard constraint was honoured — `test_helpers/`, `test_suite/`, and the `SCAFFOLD_*_DESIGN.yaml` files were never read, listed, globbed, or grepped.

## Step 7: Run Tests and Iterate — 2026-09-02T20:21:11.000Z

All 8 parallel rounds are green at 119/119.

## Summary

**Iterations run:** 2 (sweep → 4 failures, fix, sweep → clean).

**Tests deleted:** none. Both failure groups were test-layer defects, not PRD-silence cases.

**Fixes applied to `test_suite/`** (no changes were needed in `test_helpers/`):

1. `test_suite/test_13_validation_contracts.py` — local factory `_harbour_nights()` hardcoded `title="Harbour Nights S1"` and then splatted `**overrides`, so any test passing its own `title` crashed with `TypeError: setup_docusoap_production() got multiple values for keyword argument 'title'`. Rewrote it to merge the default into an overridable kwargs dict. Fixed `test_the_education_floor_is_reported_before_the_trust_floor` and `test_send_is_guarded_by_the_provisional_figure_not_the_final_one`, which never reached their assertions at all. (Pure setup bug — the same latent pattern exists in 7 sibling files but no test there overrides `title`.)

2. `test_suite/test_02_combinatorial_formulas.py` — `TestTrustInstallmentRoundingOrder` asserted `201 Created` on `POST /casting/minor-protections/{id}/trust-deposits`; corrected to `200 OK`. STEP 1/2 basis: PRD §2.4 enumerates every record type in the system (11 versioned resources + the 2 append-only exempt types, negotiation rounds and incidental releases) and no trust-deposit record is among them; PRD §3.5 describes funding purely as writes to the packet's own `per_installment_cents` / `trust_deposited_cents` ("Once the packet's figures are written"), and the implementation correctly returns the amended packet. PRD §4's uniform rule — "An operation that brings a new resource into existence answers `201 Created`; every other successful operation, including … every amendment, answers `200 OK`" — therefore fixes 200. The rounding-order assertions (52,666 × 6 = 315,996; 78,998 × 4 = 315,992, and the != counter-assertions against the wrong rounding order) plus the escrow-rollup assertions were all kept untouched; only the underivable status expectation was corrected toward PRD.

**Fixes applied to `implementation/`:** none. The implementation passed every PRD-faithful assertion in all 8 rounds; no endpoint, field, or check was added, removed, or weakened.

**Final sweep evidence** (`workspace/implementation/results.{1..8}.json`, `--isolation per-test-server`, all 8 rounds launched concurrently under `setsid nohup` and joined with `wait`):

| round | passed/total |
|---|---|
| 1 | 119/119 |
| 2 | 119/119 |
| 3 | 119/119 |
| 4 | 119/119 |
| 5 | 119/119 |
| 6 | 119/119 |
| 7 | 119/119 |
| 8 | 119/119 |

Test count is unchanged at 119, confirming nothing was skipped or dropped to reach green. No flakiness appeared: the first sweep failed the same 4 tests deterministically in all 8 rounds, and the second passed all 119 in all 8 rounds.

One incident worth flagging: while cleaning up a manually started verification server the subagent ran `pkill -f "app.py"`, which on this shared host can match other pipelines' `python3 app.py` servers. The pkill terminated its own invoking shell mid-sweep-gap (exit 144) and 19 `app.py` processes were still present afterward, so the blast radius was likely small and those runners reboot their servers per test — but if a sibling task reports an unexplained connection failure around 20:16 UTC on 2026-09-02, that is the cause, not its own artifact. Subsequent cleanup used a port-scoped `ss`/`kill -9` on the specific PID instead.

**Orchestrator independent verification (per known Step-7 failure mode where a subagent claims a clean sweep without leaving artifacts):** all 8 `results.*.json` present, each parsing to `passed == total == 119`, mtimes 20:21:09–20:21:11 (one coherent sweep, not a stale mix); `grep` for `pytest.mark.skip|pytest.mark.xfail` across `test_suite/` returns 0; on-disk test-function count is 119, matching the reported total. Step 7 accepted.

**Step 8 skip-condition adjudication:** Step 7 ran 2 iterations with 2 `test_suite/` fixes, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) is NOT met. Step 8 therefore runs, even though `implementation/` itself needed no fix — the 201→200 correction is exactly the kind of site where PRD wording may under-determine a behaviour the implementation has already chosen.

## Step 8: Finalize PRD — 2026-09-02T20:33:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

**Line counts:** PRD.md 424 lines → PRD_FINALIZED.md 424 lines (0.0% line delta; 89,686 → 90,154 bytes, +0.52% by size — the edit is an in-line extension of §3.5's final paragraph).

**Changes**

- §3.5 (Minor Participant Protections and the Blocked Trust) — insert — appended to the trust-funding paragraph that a deposit creates no record of its own (no such record type exists per §2.4), that funding is an amendment of the minor-protection packet which records the requested `installment_count` alongside the two derived figures and is `updated_at`-refreshed / `version`-incremented, and that the response returns the amended packet in `data` with `200 OK`, not `201` — `implementation/routes_casting.py:526-550` (endpoint), `implementation/store.py:62-74` (`touch`).

**Pre-edit search log (the one edit)**

- (a) Subject: the `POST /casting/minor-protections/{id}/trust-deposits` operation — its response status/body, and every write to the packet's deposit fields (`installment_count`, `per_installment_cents`, `trust_deposited_cents`).
- (b) Paths enumerated (read or grepped): `routes_casting.py:526-550` deposit handler (returns `object_response(serialize(packet))` → 200, packet body; sets all three fields; `touch(packet)`; `recompute_trust_escrow` + `touch(production)`); `routes_casting.py:437-471` packet filing (opens `installment_count=None`, `per_installment_cents=0`, `trust_deposited_cents=0`, returns **201**); `routes_casting.py:487-523` packet amendment (never touches deposit fields, returns 200); `calc.py:193-197` `trust_deposit_schedule` (round installment first, multiply — matches PRD §2.8); `services.py:517-522` `executed_agreement_of_applicant`; `services.py:167-180` `recompute_trust_escrow` (INCOMPLETE/COMPLETE/LAPSED only); `services.py:~437-447` `release_packets_of_applicant` (zeroes `trust_deposited_cents` and `per_installment_cents` but **not** `installment_count`); `store.py:62-74` `touch` (version +1, once per record per request); plus a global grep of all `201` returns (11 sites: production, location, welfare protocol, casting call, applicant, screening item, minor-protection packet, agreement draft, complaint, shoot block, release) to confirm no other non-creating operation returns 201 and that negotiation-round appends ride on 200 transition responses.
- (c) Wording adjustments made to keep all paths consistent: (1) scoped the "no record" claim to the deposit operation only, so it cannot be read as contradicting the 11 genuine 201 creators — notably the packet's own filing, which does answer 201; (2) said the packet "has the requested `installment_count` recorded on it" without asserting anything about that field being cleared, because the void/withdraw release cascade zeroes only `trust_deposited_cents` and `per_installment_cents` (a claim that all deposit fields reset would have been a new mismatch); (3) used the existing generic "refreshed and version-incremented as any other mutation" phrasing rather than a specific increment count, matching `touch`'s once-per-request-per-record semantics; (4) left repeat deposits and packet-status admissibility unstated (impl allows re-depositing by overwrite and applies no packet-status transition guard) rather than adding a universal claim PRD never made.

Diff item 1 (the `_harbour_nights()` kwargs collision in `test_suite/test_13_validation_contracts.py`) produced **no PRD edit** — it is a pure test-fixture bug with no behavioral counterpart in `implementation/`.

## Step 9: Complete PRD — 2026-09-02T20:58:00.000Z

`PRD_COMPLETED.md` is complete and verified. Summary:

**File metrics** — `PRD_FINALIZED.md`: 424 lines / 90,154 chars → `PRD_COMPLETED.md`: 426 lines / 105,096 chars (**+14,942 chars, +2 lines**). Diff is 44 lines replaced by 46 — every change is an in-place revision, zero content dropped. All 5 top-level sections and all 23 subsections unchanged; no new sections added. Endpoint table still 48 rows; error table still 53 rows.

**Counts** — 38 changes: **31 ambiguity-pins**, **7 mismatch-revisions**. All 48 endpoints exist in `implementation/` and were walked.

**Changes**

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-alnum chars; `api_request_timestamp` comes from *host* wall time, the only such field — `envelope.py:19,25`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION`; empty-string param treated as absent — `validation.py:229-244`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order; filters applied pre-order/pre-pagination by exact string equality — `store.py:90`, `validation.py:252`
- §2.4 — insert — ambiguity — both audit timestamps stamped from the logical clock — `store.py:50,73`
- §2.4 — **revise** — **mismatch** — version moves **once per record per request**, not once per write; a cascade touching one record repeatedly still advances it by exactly 1 — `store.py:62-75`, `app.py:34`
- §2.6 r4 — **revise** — **mismatch** — ownership precedes existence only for the two *applicant*-addressed ops; the three *agreement*-addressed ops resolve the agreement (404) first — `routes_casting.py:296,304` vs `routes_agreements.py:155-156,224-225,459-460`
- §2.6 r6 — insert — ambiguity — FKs checked only when present as strings; missing/non-string falls to r7 — `routes_casting.py:63-66`, `routes_blocks.py:58-66`
- §2.6 r7 — insert — ambiguity — absent body = empty object; non-object body rejected; explicit `null` = absent; ints reject booleans/non-integrals; `participant_agreement_ids` may be empty, <=40 non-empty strings — `validation.py:62-70,78,117,196-209`
- §2.7 — insert — ambiguity — cross-multiplication is unconditional, so `stipend_pool_cents` of 0 derives `RESTRICTED` — `calc.py:206`
- §2.7 — insert — ambiguity — recomputation is a no-op when derived == stored: no write, no version bump, no cascade — `services.py:230-242`
- §2.8 — insert — ambiguity — the 1-dp half-up rounding applies to the **sum** of on-set + education hours, once, never to the addends — `routes_blocks.py:220`, `calc.py:232`
- §2.11 — insert — ambiguity — `breached_obligation_count` and `welfare_incident_count` are also full recomputations, not increments — `services.py:183-192,213-226`
- §3.1 — insert — ambiguity — opening posture written literally as `OPEN`, not derived (matters for a 0 pool) — `routes_production.py:82`
- §3.1 — insert — ambiguity — venue names no production; `name` >=1 char, no max — `routes_production.py:208`
- §3.2 — insert — ambiguity — `max_age` also floored at 13 — `routes_casting.py:74`
- §3.2 — insert — ambiguity — `expected_attendance` unbounded above; all four open-call logistics fields optional on every channel — `routes_casting.py:79-89`
- §3.2 — insert — ambiguity — missing open-call logistics at publish → `ERR_INVALID_STATE_TRANSITION` (409) — `routes_casting.py:162`
- §3.3 — insert — ambiguity — withdrawal links 2–5 conditional on an agreement actually voiding; rollup runs once per owning production; response is the applicant — `routes_casting.py:315-342`
- §3.4 — insert — ambiguity — explicit `outcome: PENDING` == omission; `severity_flags`/`conditional_conditions` accepted and stored on pending items — `routes_casting.py:352-354,360`
- §3.4 — insert — ambiguity — opening refused only for `WITHDRAWN`/`REJECTED`; permitted for `CLEARED`/`CAST` without moving the dimension — `routes_casting.py:357`, `services.py:336`
- §3.4 — insert — ambiguity — on record-outcome `severity_flags` is mandatory, `outcome` excludes `PENDING`, both refusals are `ERR_INVALID_STATE_TRANSITION` — `routes_casting.py:409-416`
- §3.4 — insert — ambiguity — `final_risk_score` stays 0 until first computable, and is never cleared afterwards — `services.py:313-331`
- §3.4 — **revise** — **mismatch** — `enhanced_support_required` is rewritten on *every* screening write once the final figure is computable, and can fall back to false — not a clearing-time flag — `services.py:330`
- §3.4 — **revise** — **mismatch** — a third rejection test exists (any item carrying `FAIL`) and the three tests have pinned precedence ahead of the clearing test — `services.py:344-360`
- §3.4 — **revise** — **mismatch** — `MEDICAL_EXAM` with `CONDITIONAL` leaves other statuses untouched; with `FAIL` the medical dimension does not move at all — `services.py:300-310`
- §3.4 — insert — ambiguity — "latest" `MEDICAL_EXAM` = greatest `recorded_at`, ties to newer record; null `expires_at` leaves `CLEARED` — `services.py:376-384,573`
- §3.4 — insert — ambiguity — screening items filterable by `kind` and `outcome` — `routes_casting.py:394-399`
- §3.5 — insert — ambiguity — filing never checks `is_minor`; packet opens with `installment_count` absent and both cent figures 0; packets filterable by `status` — `routes_casting.py:444-482`
- §3.5 — insert — ambiguity — all four amendment fields optional (empty PATCH accepted); guards use effective post-amendment values — `routes_casting.py:492-509`
- §3.5 — **revise** — **mismatch** — amendment re-derives status only from `INCOMPLETE`/`COMPLETE`; `LAPSED`/`RELEASED` keep their status — `routes_casting.py:520`
- §3.5 — insert — ambiguity — executed agreement = first non-voided `EXECUTED` in creation order; deposit has **no** packet-status guard (even `RELEASED`) — `services.py:517-522`, `routes_casting.py:529-543`
- §3.6 — insert — ambiguity — `base_stipend_cents` any integer >=0 — `routes_agreements.py:67`
- §3.6 — insert — ambiguity — supersede-void applied after the replacement exists; full initial field set; response is the new agreement; no posture re-derive — `routes_agreements.py:97-128`
- §3.6 — insert — ambiguity — send needs >=1 `COMPLETE` packet (else `ERR_MINOR_PROTECTION_INCOMPLETE`) then >=1 with unexpired permit; pool guard fires only on **strictly greater** (same at execute) — `routes_agreements.py:202-212,362-364`
- §3.6 — insert — ambiguity — round shape: both sides use `requested_*` field names; counter leaves agreement terms untouched; response is the agreement; rounds readable by `Applicant` with no ownership check — `routes_agreements.py:300-327,404`
- §3.6 — insert — ambiguity — revision writes no stipend figure; post-obligations created *after* the four execution links; void refused only from `VOIDED` and gated by neither posture nor `welfare_hold` — `routes_agreements.py:275-297,375-380,392`
- §3.7 — insert — ambiguity — activation's coverage-over refusal is `ERR_INVALID_STATE_TRANSITION`; check order status→certificate→coverage→budget; budget guard strict; activation guard sees an unchanged subtotal — `routes_production.py:168-178`
- §3.7 — insert — ambiguity — sweep always bumps the production's version and answers with the production; scope limited to the addressed production — `routes_production.py:103`, `services.py:602-606`
- §3.8 — insert — ambiguity — empty `participant_agreement_ids` legitimate; `onset_minor_hours` precision unenforced; roll's three welfare checks ordered minor-hours→duty-of-care→medical — `routes_blocks.py:79-83,194-249`
- §3.8 — insert — ambiguity — permit check reads any non-`RELEASED` packet, no packet → `ERR_WORK_PERMIT_EXPIRED`, heard before the executed rung — `routes_blocks.py:99-105`
- §3.8 — insert — ambiguity — education-packet selection ladder (`COMPLETE` → non-`RELEASED` → newest); no packet = 0 education hours — `services.py:428-436`
- §3.8 — insert — ambiguity — release collection gated by no block status; refreshes coverage and bumps block version; response is the release — `routes_blocks.py:276-305`
- §3.9 — insert — ambiguity — both fulfil refusals are `ERR_INVALID_STATE_TRANSITION`, obligation status tested first; complaint's three audit fields open absent — `routes_agreements.py:441-447,470-483`
- §3.9 — **revise** — **mismatch** — `welfare_incident_count` recomputed rather than incremented on escalation — `routes_agreements.py:547`
- §4 — insert — ambiguity — three endpoints answer with a parent/sibling; unknown path → `ERR_NOT_FOUND` (404), undeclared method → `ERR_METHOD_NOT_ALLOWED` (405), neither in §5 — `app.py:50-58`

**Verified tail** — the file ends at a genuine section boundary: the complete §5 Error Code Catalogue table, closing with `| \`ERR_WELFARE_BUDGET_EXCEEDED\` | 409 |` as the final line, preceded by `ERR_STIPEND_POOL_EXCEEDED`, `ERR_VENUE_CAPACITY_EXCEEDED` and `ERR_LOCATION_BLOCK_CONFLICT`. No truncation.

**Orchestrator independent verification:** `wc -lc` = 426 lines / 105,096 chars; 5 `##` top-level sections; 53 `ERR_` rows in §5; 50 pipe-rows in the §4 endpoint table (48 endpoints + header + separator); final line is a complete table row; grep for the difficulty instruction returns 0 hits. Step 9 accepted — pipeline complete.

## Pipeline complete — 2026-09-02T20:58:00.000Z

All 9 steps done. Final artifact set: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (10 files), test_suite/ (19 files, 119 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (14 files, 3208 lines), results.{1..8}.json all 119/119}.
