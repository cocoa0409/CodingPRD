# Worklog — task_2541_draft_beer_line_cleaning_dispense_service

## Step 1: Create task directory — 2026-09-03T08:39:46.926Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2541_draft_beer_line_cleaning_dispense_service` and its `workspace/` subdirectory. Index 2541 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T10:31:38.884Z

All three scaffold artifacts are complete and lint-clean.

## Files written (`/home/ubuntu/github/CodingPRD/tasks/task_2541_draft_beer_line_cleaning_dispense_service/`)

| File | Lines | Top-level key(s) |
|---|---|---|
| `SCAFFOLD.yaml` | 3645 | 13 keys, §1.0–§1.7 only — no `scaffold_difficulty_design`, no `scaffold_corner_design` |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2565 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4492 | `scaffold_corner_design` |

## Scaffold counts (§1.0–§1.7)
- 14 entities, 10 state machines (11 dimensions incl. BrewerProgram), 2 OCC concurrency rules (both 412)
- 7 calculation rules (2 dual-variant: `visit_charge_settlement`, `yield_loss_estimate`)
- 55 priority-ordered validations, 69 error codes
- 59 endpoints (28 GET, 30 POST business, 1 test-driving clock), 5 roles under segregation of duties

## Design instances
- **§1.8 difficulty**: 9 rules × 21 instances (every rule >= 2)
- **§1.9 corner**: 53 active + 25 `excluded_because` stubs across all 9 claim-extraction sections — entities 12, state_machines 11(+5), calculations 4(+10), validations 7(+3), endpoints 4, errors 7(+5), rbac 4, cross_cutting_layers 3(+2), consistency_model 1

## Verification
```
§1.5 endpoints declared:    59
§1.1 entities declared:     14
§1.8 instances scanned:     21
§1.9 instances scanned:     53
Calls scanned (§1.8+§1.9):  902

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional self-checks passed: all three files parse as YAML; instance `name` values unique across the union of both design files (0 duplicates); every stub's cited `difficulty_instance` resolves to a real §1.8 instance name; no stale `effective_from: 2026-09-01` remains (the P43 activation bug is gone).

Notable design decisions worth flagging to the caller:
- **§1.5 was reshaped, not weakened**, to make `ERR_LOT_RELEASE_BLOCKED` reachable: a `ChemicalLot DEPLETED → QUARANTINED` transition was added (with matching endpoint description and side-effect text), enabling the chain lot 0.35 L → cycle draws 0.31 → DEPLETED at 0.040 → quarantine → release 409 → cycle void refills to 0.350 → release 200.
- One stub was upgraded to a full active instance after grep showed its claimed §1.8 coverage did not exist (`ERR_VISIT_ALREADY_SETTLED` had zero hits in the difficulty file) — now `corner_voiding_a_cycle_on_a_settled_visit_is_refused`.
- Version assertions are confined to `ServiceAccount` and `BeerLine`, the only entities whose §1.2.1 rules increment `version`; forbidden concurrency vocabulary is absent throughout.

## Step 3: Copy shared files — 2026-09-03T10:31:52.221Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T10:55:00.000Z

PRD generation for task 2541 is complete.

**Output:** `workspace/PRD.md` — **503 lines**, built in 14 chunked heredoc appends (each verified with `tail`), ending at the last row of the §5 error table with no audit footer.

**Section list (24 headings):** §1 Introduction; §2 Global Specifications (2.1 RBAC · 2.2 API Response Structure verbatim · 2.3 Pagination · 2.4 Identity/Timestamps/Version · 2.5 Logical Service Clock · 2.6 Numeric Precision · 2.7 OCC on Account and Line Writes · 2.8 Screening Ladder · 2.9 Resolving References · 2.10 Cascade Discipline); §3 Business Logic (3.1 Venue Onboarding · 3.2 Line Register + Cleaning-Due Projection · 3.3 Route Board · 3.4 Chemistry Inventory + Alternating Cycle · 3.5 Gas Blend/Pressure Balancing · 3.6 Component Inspections + Parts · 3.7 Visit Close-Out · 3.8 Complaints/Diagnosis/Yield Loss · 3.9 Glycol/Cooler/Enforcement); §4 Endpoint Definitions (59 rows); §5 Error Code Catalogue (69 rows).

**Hard Contract results**
- **Contract 1 — Field-Name Coverage: PASS.** 155 required names (130 entity fields + 76 POST body inputs + 31 GET query params + 14 path params, deduplicated), 0 missing, two independent verification passes. One gap found and fixed mid-run: path parameters existed only as braced tokens, so §2.9 now also names them bare.
- **Contract 2 — Rule Coverage: PASS.** All 55 validation error IDs, all 69 catalogue codes, both OCC rules, all 7 calculations appear in §1–§4 prose. All 10 state machines / 11 dimensions walked transition by transition. The three deliberate priority inversions are stated twice each (§2.8 + owning workflow): `ERR_ACCOUNT_NOT_ACTIVE` over `ERR_OUTSIDE_ACCESS_WINDOW`, `ERR_PART_TYPE_MISMATCH` over `ERR_PART_OUT_OF_STOCK`, `ERR_TECHNICIAN_NOT_CAUSTIC_CERTIFIED` over `ERR_CHEMICAL_PARITY_VIOLATION`.
- **Contract 3 — §3 Path Purity: PASS.** 329 distinct backticked tokens in §3; zero start with `/`, zero are a bare HTTP method, zero combine method+path.

**Other completeness checks run:** §4 = 59 rows, every scaffold endpoint path present (0 missing); §5 = 69 rows against 69 scaffold codes; §2.2 diffed byte-for-byte against the canonical response-structure section; no fuzzy words, pseudocode operators, or scaffold constant identifiers leaked.

**Three scaffold inconsistencies resolved by judgement** (flagged for the test suite):
1. `CleaningCycle.compliance_result` field description grades concentration → contact time → temperature, while `chemical_cycle_dosing` step 6 pins temperature → concentration → contact time. PRD follows the calculation (temperature first).
2. `visit_charge_settlement` counts "any POSTED PASS cycle" while `billable_line_count` says the **newest** posted cycle must be PASS. PRD follows the newest-cycle rule (matches return-to-service and projection tie-breaks).
3. `QualityComplaint` defines `ESCALATED → RESOLVED`, but P19 and `ERR_COMPLAINT_ALREADY_CLOSED` exclude `ESCALATED` from closure. PRD allows closure from `ESCALATED` for a `RESOLVED` disposition only, and refuses diagnostic rounds from `ESCALATED`.

Neither design YAML was opened, grepped or referenced; no sibling task directory was read.

**Orchestrator truncation check (independent):** `tail` confirms PRD.md ends at a genuine final table row, not mid-sentence. Cross-verified by script: 69/69 error rows, 59/59 endpoint rows, 46/46 distinct `/draft-service/...` paths present, 69/69 scaffold ERR codes present (the 70th scaffold token is the literal placeholder `ERR_XXX`). No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T11:29:44.000Z

The implementation is complete.

## Files written — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded launcher (`if ! python3 -c "import flask"` → pip install; `exec python3 app.py`), executable |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 54 | Flask app factory, 5 blueprints, `ApiError`/`HTTPException`/`Exception` handlers all emitting the envelope, `0.0.0.0:$PORT` (default 10000) |
| `common.py` | 211 | Decimal helpers (`ROUND_HALF_UP`/`CEILING`/`FLOOR`), ISO-8601 `.mmmZ` timestamps, ids, role constants, every calculation constant |
| `errors.py` | 121 | `ApiError` + the full 69-code status catalog |
| `store.py` | 179 | 14 in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), `new_row`, per-request-deduped `touch()` |
| `envelope.py` | 52 | `meta`/`response_type`/`data` object, array (limit/offset/total_count/has_more) and error envelopes |
| `security.py` | 71 | `X-User-ID`/`X-User-Role` auth, RBAC `guard`, venue scope, technician assignment, segregation of duties |
| `shape.py` | 194 | ladder step 4: unknown/missing/mistyped/out-of-range body fields, pagination and query coercion |
| `calc.py` | 210 | the 7 calculation rules (dosing, gas balance, visit charge x2 variants, yield loss x2, funding waterfall, glycol health) |
| `projections.py` | 258 | read-time projections (`next_due_at`, `days_overdue`, `compliance_flag`, applied gas, loop health) + cascade hops |
| `serializers.py` | 260 | per-entity JSON projections (inspections/readings immutable: `id`+`created_at` only) |
| `settlement.py` | 149 | provisional/settled charge runs, brewer waterfall, ledger sync, EXHAUSTED cascade, dispute reversal |
| `helpers.py` | 82 | path/body FK resolution tables, list plumbing |
| `routes_core.py` | 339 | clock, accounts x4, contracts x4, beer-lines x4 |
| `routes_registry.py` | 242 | technicians x3, chemical-lots x4, parts x3, brewer-programs x5 |
| `routes_visits.py` | 307 | service-visits x8 (booking screen P30–P34, start, complete-work, reschedule, verification, waiver) |
| `routes_work.py` | 351 | cleaning-cycles x4, balance-records x4, component-inspections x3 |
| `routes_quality.py` | 279 | quality-complaints x6, glycol-loops x3, cooler-readings x3 |

**3370 lines total.** Endpoint count verified from the URL map: **59 routes = 28 GET + 31 POST** (30 business POSTs + the clock), exactly matching the SCAFFOLD endpoint table. Storage is in-memory only; a grep confirms no seeding, no SQLite, no file writes.

## Smoke test (port 51831, launched via `PORT=… bash start.sh`, killed by PID resolved from the port)

- create + read account: 201/200, envelope and `2026-08-01T00:00:00.000Z` clock correct; the `glycol_system_present` account cascade-created a loop discoverable only through `GET /glycol-loops?account_id=` (35.0/12.0/28.0, health 100.0, NORMAL).
- deliberate errors all shaped correctly: `ERR_INVALID_REQUEST` 400 (window end <= start, `limit=200`), `ERR_UNAUTHENTICATED` 401, `ERR_UNAUTHORIZED` 403, `ERR_VISIT_NOT_FOUND` 404, `ERR_STALE_ACCOUNT_VERSION` 412, `ERR_DUPLICATE_LINE_NUMBER` 409.
- full money path reproduced the PRD's worked numbers exactly: contract 4175 @ 21 days → multiplier 1.10 → per-line 4593; 3 serviced lines → provisional subtotal **13779**; one `FAIL_CONTACT_TIME` → settled subtotal **9186**; waterfall at `co_pay_bps` 2000 → brewer **7348**, due 9838, program consumed 7348; dispute reversed everything to 0 and credited the program back. Account version went 1→3 across draft+activate, `billing_mode` PROGRAM_BILL, failing cycle put its line OUT_OF_SERVICE/NON_COMPLIANT without tripping the 4-line suspension threshold. Complaint settled variant returned 19.00 L / 9120 cents (18.5 measured + 1 day x 0.5 allowance), consistent with the PRD's 19.50/9360 two-day example.

Two judgment calls worth flagging: `measured_waste_liters` is enforced as required only for `disposition=RESOLVED` (PRD "every resolution requires"), and verification checks the verification dimension before `work_status` per the PRD's explicit "the platform first checks that the verification dimension permits the decision at all", which inverts the scaffold's P15/P18 numbering.

**Orchestrator note on Steps 5/6 concurrency:** the two agents were launched in back-to-back messages ~80 s apart rather than in a single message. Physical isolation was preserved regardless — `test_suite/` was not created on disk until 11:09, well after the implementation agent began at ~10:57, and the implementation agent was additionally given an explicit absolute prohibition on reading `test_suite/` or `test_helpers/`.

## Step 5: Generate unit tests — 2026-09-03T12:06:25.000Z

All work is complete. Final state of the deliverable:

## Files written

`test_helpers/` (9 files, 2832 lines)

| File | Lines |
|---|---|
| `__init__.py` | 112 |
| `api_client.py` | 518 |
| `api_errors.py` | 180 |
| `assertions.py` | 356 |
| `constants.py` | 116 |
| `factories.py` | 373 |
| `fixtures.py` | 663 |
| `test_users.py` | 59 |
| `types.py` | 455 |

`test_suite/` (conftest + 20 test modules, 5089 lines)

`conftest.py` 42 · `test_01` 182 · `test_02` 316 · `test_03` 249 · `test_04` 260 · `test_05` 327 · `test_06` 226 · `test_07` 210 · `test_08` 220 · `test_09` 204 · `test_10` 264 · `test_11` 183 · `test_12` 385 · `test_13` 150 · `test_14` 177 · `test_15` 327 · `test_16` 334 · `test_17` 224 · `test_18` 358 · `test_19` 215 · `test_20` 236

## Coverage — 95 tests, zero gaps

- **Queue A (§1.8 difficulty): 21/21 instances, 42 tests**, every instance carrying at least 2 tests (`test_01`–`test_09`).
- **Queue B (§1.9 corner): 53/53 active instances, 53 tests** (`test_10`–`test_20`), one test per instance: entities 12, state_machines 11, calculations 4, validations 7, endpoints 4, errors 7, rbac 4, cross_cutting_layers 3, consistency_model 1.
- **Nothing skipped**, and **none of the 25 `excluded_because` stubs** was translated (verified by set intersection against the yaml).

## Audits run

- Design tags: 95 tests, each with exactly one known `Design:` line, 0 unknown/dual/missing.
- PRD-citation pass: **175 quotations** extracted from docstrings, all verbatim substrings of `workspace/PRD.md`.
- Scaffold-citation pass: 0 hits for `scaffold`, `§1.x`, `excluded_because`, `priority N` or `Pnn` anywhere in generated code.
- Attribute/import pass: every `test_helpers` import, `fixtures/factories/assertions/constants` attribute and `api.*` method resolves; all 30 files compile; unused-import scan clean (two stale imports removed from `test_01`).

## Recipe/PRD conflicts resolved in the PRD's favour (asserted outcome kept PRD-derived)

1. `corner_contract_program_link_...` and `corner_contract_create_carrying_the_pre_activation_account_version_is_stale` both assumed only activation bumps `ServiceAccount.version`; §3.1 says drafting bumps it too. Tests assert 2 after the draft and 3 after activation, and the stale-version retry re-reads the live token instead of hard-coding 2.
2. `corner_the_auditor_who_escalated_...` used `finding_code: BIOFILM_IN_RUN`; replaced with the declared `LINE_SOIL`.
3. `corner_booking_an_inactive_technician_...` used `certification_level: JOURNEYMAN`; replaced with `CERTIFIED` (outcome does not depend on it).
4. `corner_one_line_out_of_three_...` asserted `abandon_reason == null` on the untouched visit; §3.3 pins a freshly booked visit's `abandon_reason` at `NONE`, so the test asserts `NONE`.

Earlier in the run the same rule was applied to the complaint-escalation and `part_sku_id`-on-`CLEANED` recipes, and six over-specified timestamp equalities were routed through a new `assert_instant` helper in `assertions.py` so a `.000Z` rendering cannot fail a test the PRD does not constrain.

No sibling task directory was read, and nothing under `workspace/implementation/` was read, written or executed.

## Step 7: Run tests and iterate — 2026-09-03T12:17:26.487Z

All 8 rounds now pass 95/95. Done.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each, `setsid nohup`, per-test-server isolation).

**Iteration 1 result:** 67/95 in all 8 rounds — 28 failing tests, identical union in every round (fully deterministic, no flakiness signal). Two root causes, both real defects, no ambiguity requiring PRD-derivability adjudication.

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule (error-code catalogue §5, ladder §2.8, glycol scoring §3.9, cooler-reading `source` derivation §2.1/§3.9) and none collapsed under unique-derivability — both failures were mechanical bugs, not interpretation disputes.

**Fixes applied to `test_suite/`** (STEP 2 — test bug, in the test layer):
- `test_03_workflow_state_machines.py`, `test_05_validation_precedence.py`, `test_06_boundary_edges.py`, `test_07_cross_entity_gates.py`, `test_08_scheduling_overlap.py`, `test_10_entity_reads.py`, `test_11_entity_inputs.py` — 22 tests referenced constants as `ApiErrorId.ERR_<NAME>` while `test_helpers/api_errors.py` declares the members unprefixed (`ApiErrorId.<NAME> = "ERR_<NAME>"`). Every such reference raised `AttributeError` at assert time, so the test died before it could evaluate the response. Normalized `ApiErrorId.ERR_` → `ApiErrorId.` across the suite. This changes no expected value — the resolved string constants (`"ERR_INVALID_REQUEST"`, `"ERR_VENUE_SLOT_CONFLICT"`, etc.) and their PRD-pinned HTTP statuses are unchanged, so no assertion was weakened.

**Fixes applied to `implementation/`:**
- `workspace/implementation/helpers.py`, `COLLECTION_FOR` map — the body-FK lookup table was missing a `"glycol_loop_id"` entry, even though `BODY_ERRORS` declared `glycol_loop_id → ERR_GLYCOL_LOOP_NOT_FOUND` per PRD §2.9. `resolve_body("glycol_loop_id", ...)` in `routes_quality.create_reading` therefore raised `KeyError` and `POST /draft-service/cooler-readings` returned HTTP 500 for *every* call, breaking 6 tests at setup. Added `"glycol_loop_id": store.glycol_loops`. `glycol_loop_id` was the only `BODY_ERRORS` key absent from `COLLECTION_FOR`.

**Final sweep evidence** (all rounds complete JSON, `failed == 0`, `errors == 0`, 95 tests each, ~172 s/round):

| round | passed/total |
|---|---|
| results.1.json | 95/95 |
| results.2.json | 95/95 |
| results.3.json | 95/95 |
| results.4.json | 95/95 |
| results.5.json | 95/95 |
| results.6.json | 95/95 |
| results.7.json | 95/95 |
| results.8.json | 95/95 |

Sweep log contains zero `ERROR` lines and zero `Terminated` occurrences, so no round was reaped. Also confirmed `implementation/` does no file/SQLite/tmp persistence — storage is in-memory only, wiped on every `start.sh` reboot.

**Orchestrator independent verification:** re-read all 8 `results.*.json` off disk (each ~28.7 KB, mtime 12:15) — every one parses and reports `passed=95 total=95 failed=0 errors=0`; `grep -c Terminated workspace/sweep.log` = 0. The sweep artifacts are real, not merely claimed.

## Step 8: Finalize PRD — 2026-09-03T12:22:00.000Z

## Result

`workspace/PRD_FINALIZED.md` produced as a **byte-identical copy** of `PRD.md` (md5 `118da47b59c6e7a29bcedacef49ef11c` for both). **Zero PRD edits were warranted.**

- PRD.md: 503 lines. PRD_FINALIZED.md: 503 lines. Delta: 0 lines, **0.0 %**.
- Change bullets: none.

## Why zero edits

Both `<step_7_diff>` items are non-PRD-bearing:

**Item 1 — `implementation/helpers.py:52`, `COLLECTION_FOR["glycol_loop_id"]`.** A pure mechanical omission that made `resolve_body("glycol_loop_id", …)` raise `KeyError` → HTTP 500 on every `POST /draft-service/cooler-readings`. The behavior the fix restores is already stated verbatim in the PRD in three independent places: §2.9 ¶2 lists `glycol_loop_id → ERR_GLYCOL_LOOP_NOT_FOUND` among the body-FK codes, §5 pins that code at HTTP 404, and §2.8 step 5 places body-reference resolution after the shape check and before the venue-ownership scope check. The impl now matches all three exactly. Nothing about the restored path is PRD-silent.

**Item 2 — `test_suite/*` `ApiErrorId.ERR_<NAME>` → `ApiErrorId.<NAME>`.** Confirmed against `test_helpers/api_errors.py:16-39`: members are declared unprefixed. A test-layer symbol-name bug with zero behavioral content, so it carries no PRD implication.

Post-fix sweep evidence in `workspace/implementation/results.{1..8}.json`: **95/95 passed in all eight rounds**, no failures or errors.

## Pre-edit search log (candidate edits considered and rejected)

**Candidate A — subject: body-FK resolution of `glycol_loop_id` on `POST /cooler-readings`.**
(a) Subject: which error/status a bad `glycol_loop_id` yields, and where in the ladder it fires.
(b) Paths enumerated and read: `helpers.py` (`PATH_ERRORS`, `BODY_ERRORS`, `COLLECTION_FOR`, `resolve_path`, `resolve_body`); `routes_quality.py:242-262` (`create_reading` — order: `parse_body` → `resolve_body` → `venue_scope` → `require_glycol_system`); `routes_quality.py:217-237` (`service_loop`, the parallel `visit_id` body-FK + `loop_id` path-FK endpoint); `routes_quality.py:193-197` (`require_glycol_system`); `security.py:52-55` (`venue_scope` — no-ops for non-`VenueManager`); `store.py:169-171` (`account_loop`). Cross-checked `BODY_ERRORS` keys against `COLLECTION_FOR` keys: `glycol_loop_id` was the sole absentee.
(c) Wording adjustment: none — no edit committed. Every enumerated path is already correctly described by §2.8 step 5/6/12, §2.9 ¶2 and §5.

**Candidate B — subject: loop `health_score` / `version` on reading post (blast radius of the same fix).**
(a) Subject: whether posting a cooler reading mutates the `GlycolLoop` row.
(b) Paths enumerated and read: `projections.py:204-216` (`loop_window_temps`, `loop_projection`, `loop_status` — all lazy, nothing persisted); `serializers.py:234-247` (`glycol_loop` computes `health_score`/`status`/`window_avg_cooler_temp_f` at serialize time); `routes_quality.py:253-262` (`create_reading` never calls `store.touch(loop)`); `routes_quality.py:232-236` (`service_loop` does, and only there); `store.py:93-108` (`touch`).
(c) Wording adjustment: none — no edit committed. PRD is already compatible on every enumerated path; pinning it would be manufactured scope plus a NO-NEW-MISMATCH hazard against `service_loop`.

## Step 9: Complete PRD — 2026-09-03T12:45:37.541Z

Run as **three sequential file-partitioned passes** over `workspace/implementation/` (17 modules, 3360 lines), each editing `workspace/PRD_COMPLETED.md` in place with exact-string Edits so no pass could clobber another. Orchestrator seeded `PRD_COMPLETED.md` as a copy of `PRD_FINALIZED.md` before pass 1.

### Pass 1 — cross-cutting layer (`app.py`, `common.py`, `errors.py`, `store.py`, `envelope.py`, `security.py`, `shape.py`, `helpers.py`)

503 → 507 lines, 108,468 → 114,613 chars (+6,145). **12 ambiguity-pins, 0 mismatch-revisions** — the eight modules agreed with the PRD everywhere it spoke (`errors.py`'s status map is byte-for-byte consistent with the §5 table; the ladder order in `security.py`/`helpers.py`/`shape.py` matches §2.8), so everything found was silence.

- §2.1 — insert — ambiguity — both headers whitespace-stripped before use; role matched case-sensitively — `security.py:15-26`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 upper-case-alnum chars — `common.py:111-115`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the logical clock, not real time; present on error envelopes too — `envelope.py:8-15`
- §2.3 — insert — ambiguity — `limit`/`offset` parsing: plain base-ten ints, whitespace tolerated, empty falls back to default, fraction/`+`/zero-padded/text is `ERR_INVALID_REQUEST`; `offset` unbounded — `shape.py:147-162`
- §2.3 — insert — ambiguity — **universal tiebreak**: equal `created_at` resolves by insertion order, the final key of every ordering rule in either direction — `store.py:123-133`
- §2.3 — insert — ambiguity — `has_more` is exactly `offset + len(page) < total_count` — `envelope.py:36`
- §2.4 — insert — ambiguity — timestamps truncate sub-millisecond precision (never round); null instants render `null` — `common.py:49-54`
- §2.4 — insert — ambiguity — `version` moves at most once per request even across multi-field writes or two cascade paths — `store.py:93-108`
- §2.6 — insert — ambiguity — named decimal places are derivation precision, not input validation: client decimals stored/echoed unrounded; JSON numbers drop trailing zeros; money as integer cents — `shape.py:80-87`, `common.py:40-44`
- §2.7 — insert — ambiguity — `expected_line_version` must be >= 0 (negative is 400 at shape); any integer is shape-legal for `expected_account_version` and a non-match is 412 — `shape.py:101-111`
- §2.8 item 4 — insert — ambiguity — full shape mechanics: absent/empty/`null` body reads as `{}`; non-object rejected; unknown-field sweep precedes field checks; no cross-type coercion; no string field accepts `""`; explicit `null` only for `brewer_program_id`; date/datetime formats — `shape.py:38-136`, `common.py:57-84`
- §2.9 — insert — ambiguity — invalid enum filter is `ERR_INVALID_REQUEST` not an empty page; boolean filters accept only `true`/`false`; empty filter ignored; identifier filters never resolved (unknown id → empty page, never 404); undeclared params ignored — `shape.py:165-189`, `helpers.py:82-83`
- §4 — insert — ambiguity — trailing slash accepted as equivalent — `app.py:24`
- §5 — insert — ambiguity — unrouted path / unsupported method answer the standard envelope with `ERR_INVALID_REQUEST` at 404/405 rather than 400 — `app.py:35-40`

Deliberate omission: `app.py:42-44`'s catch-all 500 emits `ERR_INVALID_REQUEST` at 500, but it is unreachable defensive code.

### Pass 2 — derivation layer (`calc.py`, `settlement.py`, `projections.py`, `serializers.py`)

507 → 507 lines, 114,613 → 119,002 bytes (+4,389). **8 ambiguity-pins, 8 mismatch-revisions.**

- §2.4 — insert — ambiguity — calendar-date fields render as bare ten characters, not instants — `serializers.py:88,127`
- §2.5 — insert — ambiguity — line/loop derived figures are read-time projections, so a clock set moves no `updated_at`/`version` — `projections.py:209,45`, `serializers.py:58-62,235`
- §2.10 — insert — ambiguity — `dispute_reason`, `waiver_note`, `reopen_reason`, `end_note` are stored but never serialized, while `void_reason`/`decision_note` are — `serializers.py:121,168,189,210`
- §3.1 — revise — mismatch — programme-revival cascade: contracts all recomputed before any account, each affected account visited once, `billing_mode` recompute defined once universally (`PROGRAM_BILL` iff the account's `ACTIVE` contract is `BREWER_FUNDED`) — `settlement.py:26-39`, `projections.py:125-133`
- §3.1 — revise — mismatch — programme-end cascade refers to that same recompute rule instead of "to `DIRECT_BILL`" — `projections.py:125-133`
- §3.2 — insert — ambiguity — `next_due_at` reads the *governing* contract (active, else newest non-`EXPIRED` by descending `created_at`); null when neither exists — `projections.py:25-42`
- §3.2 — revise — mismatch — return-to-service clears only the grade reason; the calendar reason can still leave `compliance_flag` `NON_COMPLIANT` — `projections.py:52-57`
- §3.3 — revise — mismatch — the `IN_PROGRESS → ABANDONED` edge does not exist; only `SCHEDULED` visits are abandoned — `projections.py:185-194`
- §3.4 — insert — ambiguity — the suspension threshold reads only the `ACTIVE` contract (no fallback), so no active contract means no suspension; non-`ACTIVE` accounts skipped — `projections.py:160-170`
- §3.4 — insert — ambiguity — the suspension cascade also recomputes `billing_mode` (landing on `DIRECT_BILL`) — `projections.py:173-182`
- §3.4 — insert — ambiguity — a void recomputes both counts under the *provisional* definitions and moves no money figure — `settlement.py:68-78`
- §3.7 — insert — mismatch — both charge variants use the governing contract; with no non-expired contract cleaning is 0, charge is parts only, and a settled run still reaches `SETTLED` with `brewer_funded_cents` 0 — `settlement.py:9-16,49-105`
- §3.7 — revise — mismatch — waterfall reads that same governing contract, not "the `ACTIVE` contract" — `settlement.py:107-120`
- §3.7 — revise — mismatch — dispute reversal: programme reached via the governing contract at dispute time, untouched when nothing was funded, revival cascade covers only `DRAFT`/`ACTIVE`/`SUSPENDED` in ascending `created_at` — `settlement.py:131-144`
- §3.7 — revise — mismatch — exhaustion cascade includes `DRAFT` contracts and uses the §3.1 `billing_mode` rule — `settlement.py:26-31,127-128`
- §3.8 — insert — ambiguity — the days-open count for settled yield loss has no floor or cap (clock rewind carries a negative count through) — `calc.py:149-154`

`calc.py` needed no formula corrections — dosing, gas balance, visit charge, yield loss, waterfall and glycol health were already pinned to the exact rounding order, tie-breaks and boundary inclusivity the code implements.

### Pass 3 — endpoint layer (`routes_core.py`, `routes_registry.py`, `routes_visits.py`, `routes_work.py`, `routes_quality.py`)

507 → 507 lines, 119,002 → 125,077 bytes (+6,075). **15 ambiguity-pins, 6 mismatch-revisions.**

Mismatches:
- §3.1 — revise — mismatch — contract activation screens account-state → programme-state → `effective_from`, not `effective_from` first — `routes_core.py:214-223`
- §3.2 — revise — mismatch — line registration requires **at least** one `ACTIVE` contract (earliest-created governs), and `ERR_DUPLICATE_LINE_NUMBER` screens above `ERR_CONTRACT_LINE_LIMIT_EXCEEDED`; "Three conditions" → "Four" — `routes_core.py:273-280`
- §3.3 — revise — mismatch — visit `start` order is assignment → SCHEDULED → account ACTIVE → date, and the access window is not re-checked at arrival — `routes_visits.py:166-173`
- §4 (`/start` row) — revise — mismatch — description claimed the endpoint enforces the access window; it does not — `routes_visits.py:161-176`
- §3.8 — revise — mismatch — the segregation check runs on both dispositions and sits above the status gate, so re-escalating one's own escalated complaint yields `ERR_SEGREGATION_OF_DUTIES` — `routes_quality.py:133`
- §3.5 — revise — mismatch — both branch guards run above the `PROPOSED` check; a technician asking to reject gets `ERR_UNAUTHORIZED` — `routes_work.py:250-256`

Ambiguity pins: termination also recomputes `billing_mode` and does not clear `suspended_reason` (`routes_core.py:131-137`); reactivation with no non-expired contract → `ERR_LINE_COMPLIANCE_UNRESOLVED` (`:116`); account `to_status` admits exactly ACTIVE/SUSPENDED/TERMINATED (`:102`); contract `to_status` admits exactly ACTIVE/SUSPENDED/EXPIRED, `DRAFT` is a shape error (`:210-211,250-252`); `SUSPENDED → ACTIVE` re-checks neither `effective_from` nor the programme and supersedes no sibling, so two `ACTIVE` contracts are reachable and "the active contract" means earliest by `created_at` (`:233-239`, `store.py:144`); `cleaning_frequency_days` outside {14,21,28} is a shape rejection above body FK resolution (`:156-158`); `additional_cents` >= 1 and the top-up has no status gate (`routes_registry.py:217-229`); returning an already-`IN_SERVICE` line → `ERR_INVALID_REQUEST` (`routes_core.py:328-329`); wrong originating lot status → `ERR_CHEMICAL_LOT_UNAVAILABLE`, lot `to_status` admits only QUARANTINED/AVAILABLE/EXPIRED (`routes_registry.py:114-128`); duplicate `sku` → `ERR_INVALID_REQUEST` (`:146-147`); reschedule excludes the original visit from both overlap comparisons (`routes_visits.py:230`); malformed `scheduled_date` filter → `ERR_INVALID_REQUEST` (`:144-149`); `signer_name`/`dispute_reason` tolerated-and-ignored on the opposite branch (`:254-263`); the two idle round pairings are accepted, leave `status` put, still burn a round (`routes_quality.py:110-116`); reopen recomputes `open_complaint_count` and does not clear `escalated_by_user_id` (`:179-187`); the glycol gate on loop maintenance reads the loop's account, not the visit's (`:231`).

Deliberate non-edit: several workflow orderings that look inverted (verification/reopen venue-scope before own-state; closure's status gate) are already resolved by §2.8's ladder steps 6 < 8 < 9.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` md5 `3fe4eabcc6325fc00bf8ff5995ff852a` **differs** from `PRD_FINALIZED.md`/`PRD.md` (`118da47b…`) — the scan genuinely ran; 88 changed lines, 108,468 → 125,077 chars (+15.3%).
- 507 lines, ends at the last row of the §5 table (a genuine section boundary), 26 headings, §4 = 59 endpoint rows, §5 = 69 error rows.
- Totals across the three passes: **35 ambiguity-pins, 14 mismatch-revisions**, zero new sections.
- Code freeze confirmed: every file in `workspace/implementation/` and `test_suite/`/`test_helpers/` has mtime <= 12:12, while the all-green sweep artifacts are dated 12:15 — Steps 8 and 9 edited only PRD files, so the 8×95/95 result still describes the shipped code.
