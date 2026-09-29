# Worklog — task_2601_ballot_production_logic_and_accuracy_testing

## Step 1: Create task directory — 2026-09-03T17:59:00.000Z

Created pre-assigned directories `tasks/task_2601_ballot_production_logic_and_accuracy_testing/` and `tasks/task_2601_ballot_production_logic_and_accuracy_testing/workspace/`. Index 2601 was fixed by the invoking scenario number; no auto-allocation scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-03T20:51:00.000Z

All three artifacts are complete and lint-clean.

## Output files
- `SCAFFOLD.yaml` — 3,126 lines (top-level keys: scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles, segregation_of_duties_constraints; no `scaffold_*_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,307 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6,232 lines, single key `scaffold_corner_design`

## SCAFFOLD.yaml counts
12 entities · 10 state-machine blocks · 2 concurrency_rules (OCC on `expected_ballot_style_version` at POST /print-jobs, `expected_election_version` at POST /elections/{id}/reconcile) · 9 calculations · 42 validations · 58 endpoints · 49 error ids · 7 roles · 3 segregation-of-duties constraints. Profile: compliance_audit / temporal_windowing, graph topology, cyclic state machines, role_model segregation_of_duties, consistency_model immediate, difficulty beyond_expert.

## §1.8 — 9 rule ids / 22 instances
dual_variant_calc 3 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 3 · boundary_precision_check 3 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 3.

## §1.9 — all 9 guide sections / 81 instances (59 with full test_recipe, 22 `excluded_because` stubs)
entities 11 · state_machines 14 · calculations 13 · validations 16 · endpoints 8 · errors 5 · rbac 6 · complexity_layers 6 · consistency_model 2. Every stub cites an existing §1.8 instance by name and omits `test_recipe`; all 81 names are unique across both design files. **All 49 catalog error ids are asserted as a returned `error_id` by at least one instance** (verified programmatically, not just mentioned).

## Lint verdict (verbatim, final run)
```
Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  2025

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications (§1.9 generation as a §1.5 audit)
Earlier: `net_ballot_variance` default 0; `rotation_required` default false; X-Role header naming; inspect actor = WarehouseCustodian; withdraw cascade hops aligned to §1.2; `payload.withdrawn_reason`/`disqualified_reason` declared; accountability `basis` default PRELIMINARY.

This session (all written back into SCAFFOLD.yaml):
1. **deliver is atomically bulk** — POST /print-jobs/{id}/deliver description now declares no-partial-success: all manifest lines validated first, a duplicate `lot_code` or non-positive quantity is 400, a colliding `seal_number` is 409 ERR_SEAL_NUMBER_DUPLICATE, and a bad line creates no lots/custody events and leaves the invoice untouched.
2. **seal uniqueness extended to deliver**, including within-manifest self-collision.
3. **Unknown extra fields declared non-fatal** (ignored, not ERR_INVALID_REQUEST) in `request-schema-valid`.
4. **Double revision bump removed** — proof-decision REJECT no longer bumps `revision`; only the PROOF_REJECTED→PROOFING re-request does (matched §1.2 and §1.8 nl#1).
5. **`ballot-order-well-defined` was unreachable** on POST /elections/{id}/certify-ballot-order (certify already blocks duplicates); moved to POST /contests/{id}/certify with a DRAFT-or-CERTIFIED twin condition, making the guard symmetric (neither twin can certify) and the ordering pass total by construction.
6. **`candidate-state-permits-operation` extended** to certify: a CANDIDATE contest with fewer FILED candidates than `seats_open` is refused; MEASURE contests exempt.
7. **Error lists corrected** — certify gained ERR_CANDIDATE_STATE_INVALID + ERR_BALLOT_ORDER_COLLISION; certify-ballot-order lost ERR_BALLOT_ORDER_COLLISION; both §1.6 triggers rewritten.
8. `calculations.contest_ballot_ordering` step 3 rewritten to state the input set can never be ambiguous.

Two capture-shape fixes were needed to reach clean lint: envelope `total_count` cannot be captured from a list output, so two `$.data.total_count` captures were replaced by prose assertions.

## Step 3: Copy Shared Files — 2026-09-03T20:52:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2601_ballot_production_logic_and_accuracy_testing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T21:09:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **540 lines**, built with 6 chunked `cat >> ... <<'EOF'` appends (no one-shot Write).

**Final section heading:** `## 5. Error Code Reference` — the file ends on the last row of its 49-row table (`| ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT | 409 |`), a completed section boundary, not mid-sentence.

**Section list**
- `# Ballot Production and Logic & Accuracy Testing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 Resource Identity, Timestamps and the Logical Clock; 2.5 Election Phase Gating; 2.6 Error Precedence; 2.7 Nested Path Resolution and Cross-Election Isolation; 2.8 Optimistic Concurrency Control; 2.9 Integer Quantities, Basis Points and Rounding; 2.10 Cascade Semantics and Derived-Field Propagation; 2.11 The Seal Ledger and Chain of Custody; 2.12 Segregation of Duties
- `## 3. Business Logic & Workflows` — 3.1 Standing Up an Election and Certifying the Slate; 3.2 Candidate Ordering, Rotation, and the Two Layout Bases; 3.3 Precincts, the District Lattice, and Ballot Style Construction; 3.4 Language Access, Alternative Formats, and the Proofing Loop; 3.5 Contest Withdrawal: The Five-Hop Reversal; 3.6 Print Vendors, Press Windows, Quality, and the Two Invoices; 3.7 Ballot Lot Custody: Receipt, Issue, Recall, and Return; 3.8 Tabulators, Test Decks, and the Public Logic & Accuracy Test; 3.9 Deployment, Poll Close, and the Accountability Close-Out
- `## 4. API Endpoint Definitions` (58-row table, exactly 4 columns)
- `## 5. Error Code Reference` (49-row table, exactly 2 columns)

**Coverage (verified programmatically against SCAFFOLD.yaml)**
- 58/58 endpoints in the §4 table; 49/49 errors in the §5 table.
- 12/12 entities documented in §3 prose (including `CustodyEvent`, which correctly has only `id` and `created_at` from the common set).
- 42/42 validations represented: every `error_id` of every rule appears in the §1–§4 narrative (not only in the §5 table), with the 12-rank precedence table in §2.6 and the three documented `conflicts_with` tie-breaks called out explicitly.
- Both concurrency rules documented in §2.8 with field, error and 412.
- All 9 calculations translated as prose formulas; all constants present (150 bp QC hold; freight 45000/90000/150000; spoilage tier 5000 with 25/15 bp; tolerance tiers 5000/20000 with 200/100/50 bp; 40 lines per face; 60-minute early start; 30-minute setup buffer; observer minimums 2/1; capacity 1; x11/10 requirement).
- All state names across the 10 state machines (including the two independent `TabulatorUnit` axes) appear verbatim.

**Hard Contracts**
- **Contract 1 — Field-Name Coverage: PASS.** 156 required identifiers (132 entity field names + all `input`/`output`/query/body identifiers); 0 missing from backticked tokens.
- **Contract 2 — Rule Coverage: PASS.** Walked all 42 validations, both OCC rules, all 9 calculations with variants (dual-variant candidate ordering, ESTIMATE sum-then-round vs FINAL round-then-sum invoicing, PRELIMINARY vs FINAL_CANVASS reconciliation), the depth-5 withdrawal cascade, the depth-4 L&A failure cascade, the depth-3 disqualification cascade, the supersession side-effect set, and every endpoint side-effect list; sibling branches documented symmetrically (QC_PASSED/QC_HOLD incl. the QC_HOLD self-loop; PASSED/FAILED; READY/NOT_READY; BALANCED/OUT_OF_BALANCE).
- **Contract 3 — §3 Path Purity: PASS.** 314 backtick tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 are method+path pairs.

Withheld files were honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling task directory was read.

Scaffold inconsistencies resolved while writing: auth header written as `X-User-Role` canonical with `X-Role` accepted as its short form; `request-proof` documented as `CONTESTS_CERTIFIED` with the explicit widening for the `PROOF_REJECTED` re-request; `deliver` documented as *not* phase-gated (following the two agreeing sources); `precinct.ballots_received` derived from `issued_quantity` (matching the calculation); rank-70 ties stated as decided by the guard order given in each operation's §3 narrative.

**Orchestrator truncation check:** independently verified — 540 lines, last heading `## 5. Error Code Reference` at line 486, file ends on a complete 2-column table row. Not truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T21:38:00.000Z

Implementation complete for task 2601.

## Files written (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded flask install + `exec python3 app.py` (executable) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 59 | blueprint registration, `ApiError`/404/405/HTTPException/500 JSON handlers, `0.0.0.0:$PORT` (default 10000) |
| `util.py` | 118 | logical clock (default `2026-08-01T00:00:00Z`), `fmt_ts`/`parse_ts`, ids, `round_half_up`/`ceil_div`/`floor_div`/`floor_minutes` |
| `errors.py` | 66 | all 49 error IDs + HTTP statuses |
| `envelope.py` | 53 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` (10/1/100/0) |
| `store.py` | 148 | 12 in-memory dicts, empty at boot, `setf` (bumps `version` only on real change) |
| `auth.py` | 57 | `X-User-Role` (+`X-Role` fallback), `X-User-ID`, 7 roles |
| `validate.py` | 195 | schema layer (rank 30), pagination, query filters |
| `calc.py` | 248 | 8 calculation rules (rotation/layout, requirement, invoices, freight, accountability, discrepancy, readiness) |
| `derive.py` | 328 | custody ledger, derived-field recomputes, the depth-5/4/3 cascades |
| `serial.py` | 142 | per-entity field whitelists |
| `guards.py` | 43 | path 404s + phase gate |
| `routes_election.py` | 377 | elections, contests, candidates, accountability, custody events |
| `routes_style.py` | 358 | precincts, ballot styles, layout, proofs, test decks |
| `routes_print.py` | 438 | vendors, print jobs, ballot lot custody |
| `routes_tab.py` | 414 | tabulator units, L&A sessions, `/_clock/set_current_utc` |

Total ~3055 lines, every `.py` passes `python3 -m py_compile`.

## Endpoints
**58 registered**, matching the scaffold endpoint table exactly (verified by counting `app.url_map` rules and diffing against the scaffold's 58 method/path pairs). Storage is in-memory only, nothing is seeded at import or boot.

## Smoke test result
Launched via `PORT=18601 bash start.sh`, then killed by PID (never a pattern kill); the port is now free.

- **Happy path (45 calls)**: full lifecycle election -> contest -> candidates -> certify -> ballot-order freeze -> style -> language certs -> proof request/approve -> layout -> assign-style -> lock-styles -> vendor -> print job -> approve-proof -> inspect -> deliver -> receive -> issue -> tabulator -> program -> deck -> session -> observers -> clock -> start -> record-results -> deploy unit -> deploy election -> return-counts -> close-polls -> accountability -> reconcile -> seal-retention -> custody events. All 200/201, plus 401/403/400 negatives correct.
- **Restart check**: killed and relaunched on the same port; boots clean with empty state (validates `--isolation per-test-server`).
- **Negatives (25 assertions)**: every error ID correct (stale style version 412, vendor-not-secure, press capacity aggregate rule, half-open touching windows accepted, SoD, seal duplicate/mismatch, deck capacity/empty/off-style, defect>sample, pagination bounds, 404s). The only "FAIL" lines were the smoke script's own wrong 422-vs-409 guesses; a programmatic diff of `errors.ERROR_CATALOG` against the scaffold catalog shows **49/49 error IDs and HTTP statuses match exactly**.
- **Cascade test (22 assertions)**: the depth-5 contest-withdrawal reversal verified end to end — contest WITHDRAWN with null index, style PROOF_REJECTED with cleared translations and recomputed `contest_count`, job REJECTED with zeroed invoice but retained `delivered_quantity`, lot VOIDED with cleared issue fields, precinct `ballots_received` 0 / NOT_READY, election BLOCKED with `committed_print_cents` 0, and the custody ledger reading `TRANSFER_OUT, RECEIPT, ISSUE, VOID` at `sequence_index` 1–4. Invoice arithmetic verified on both bases (estimate 6000+45000; final 3300+45000).

Documented PRD-over-scaffold decisions: layout `basis` defaults to `CERTIFIED_BASIS`; `deliver` is not phase-gated; `precinct.ballots_received` sums `issued_quantity`; `lot_variance` starts at 0; seal-retention uses its own explicit guard order; rank-70 ties follow each operation's §3 narrative (job state before phase on approve-proof, style state before phase on proof-decision, election phase first elsewhere); `la_session_count` recomputed only on a passing session.

**Orchestrator note (process deviation, recorded for honesty):** Steps 5 and 6 were launched in two consecutive assistant messages rather than one, so they were not spawned in the same message as the skill requires. Physical isolation was preserved another way: Step 6's prompt hard-forbade reading `test_helpers/`/`test_suite/`, and Step 6 was launched seconds after Step 5 while Step 5 was still reading its skill spec, before any test file existed. Step 6 reported no test-directory reads.

## Step 5: Generate Unit Tests — 2026-09-03T22:05:00.000Z

Test infrastructure and test suite for task_2601 are complete at the task root (nothing was written under `workspace/`; `workspace/implementation/` was never read).

## Files written

`test_helpers/` — 8 modules, 2,127 lines
| file | lines | contents |
|---|---|---|
| `constants.py` | 263 | clock instants, 7 roles, operator ids, phase/state vocabularies, all tiered numeric constants, canonical literals |
| `api_errors.py` | 181 | all 49 error-id constants, id->HTTP-status map (registered via `set_error_http_status_map`), not-found / state-guard families, precedence ranks |
| `api_client.py` | 275 | `BallotProductionApiClient` with one method per endpoint of PRD §4 (58) plus a raw escape hatch |
| `test_users.py` | 91 | per-role header bundles, second-actor ids for segregation rules, `vendor_rep(vendor_id)` for the only entity-backed role, malformed-identity builders |
| `factories.py` | 360 | payload builders for every write operation, all with `**overrides` |
| `assertions.py` | 318 | timestamp/instant helpers, common-field and append-only-record shape checks, envelope + error-envelope checks, ordering/pagination, custody-ledger, accountability worksheet, lot conservation, printed-position helpers |
| `fixtures.py` | 596 | `Scenario` handle plus staged builders `new_election` -> `contests_certified` -> `styles_locked` -> `delivered_lot` -> `issued_lot` -> `la_passed_unit` -> `deployed_election` -> `polls_closed_election` -> `reconciled_election`, and every fine-grained step beside them |
| `__init__.py` | 21 | package exports; importing registers the error-status map |

`test_suite/` — `conftest.py` (26 lines) + 18 test files, 9,405 lines, **214 tests**.

## Coverage

- **Queue A (difficulty): 118 tests** across all 22 non-stub instances of all 9 rule_ids — minimum 3 tests per instance (floor was 2).
- **Queue B (corner): 96 tests** across all 59 non-stub instances of all 9 sections — minimum 1 per instance (errors and validations use one consolidated test per family-sweep instance).
- **0 instances skipped**; 0 of the 22 `excluded_because:` stubs translated.

## Audit results (script-verified, not self-reported)

- 214 `Design:` lines vs 214 `def test_` — exactly one tag per test, each the last docstring line, every tag resolving to a real non-stub instance in the correct queue/section; no stub tags, no unknown tags, no duplicates of test function names across files.
- All PRD citations verified as verbatim substrings of `workspace/PRD.md`; 12 wrapped citations in `test_corner_validations.py` were rewrapped so every quote is grep-survivable on one physical line.
- `py_compile` clean on all 27 files; `pytest --collect-only` collects 214 with no errors; pyflakes clean (bar one intentional `noqa` side-effect import in conftest).
- No `skip`/`xfail`/`parametrize`/sleeps/randomness; no occurrence of "scaffold" or any design-document reference in prose.

## Fixes made after the fan-out

- `assertions.assert_envelope_meta` / `assert_error_envelope` originally looked for `meta.response_type` and a top-level `error` key. PRD §2.2 puts `response_type` at the envelope top level and the error object inside `data`; both helpers are corrected.
- `constants.ELECTION_DATE` was a bare calendar date, but PRD §2.4 and §3.1 both declare `election_date` a client-supplied ISO 8601 UTC instant. It is now `"2026-11-03T00:00:00Z"`, with `ELECTION_DATE_CALENDAR_DAY` kept for the retention-window day arithmetic.

## PRD gaps worth recording (assertions dropped, instances still covered)

- **Layout `basis` default is contradictory**: §3.2 says "defaults to `CERTIFIED_BASIS`", the §4 table says PROVISIONAL_BASIS. §4's preamble defers query parameters to §3, so the endpoints test asserts the certified default and cites §3.2 plus that preamble; the difficulty tests always pass `basis` explicitly (`default-value`).
- **`lot_variance` at lot creation**: §3.6 says 0, §3.7 says null until returned — left unasserted (`default-value`).
- **`la_session_count` after a failed or merely-started session**: not uniquely derivable (`computed-field`).
- **Exact rendering of `certified_at` / `last_reconciled_at` / `retention_until`**: the three-fractional-digit rule is pinned only for `created_at`/`updated_at`, so these use ISO-format plus day-prefix assertions (`computed-field`).
- **The layout's per-contest rotation offset** has no declared response field, so rotation is proven through exact `printed_position` values instead.
- Two design recipes were overridden in the PRD's favour: the lot ledger opens with a `TRANSFER_OUT` row (7 rows, not 6), and precinct `ballots_received` is the sum of *issued* quantities (3000, not 12500).

## Step 7: Run Tests and Iterate — 2026-09-03T22:30:00.000Z

Clean sweep: **all 8 parallel rounds 214/214 passed.**

## Iterations run
2 (iteration 1: 199/214 in all 8 rounds — 15 failures, fully deterministic, no flakiness; iteration 2: 214/214 in all 8 rounds).

## Tests deleted
None. One assertion was removed under STEP 1c (partial coverage):

- `test_suite/test_corner_entities.py::test_en_issued_lot_return_counters_zero_and_variance_null` -> renamed `test_en_issued_lot_return_counters_zero`; the `lot_variance is None` assertion was dropped (**DEFAULT-VALUE SILENCE / PRD self-contradiction**). PRD §3.6 says a lot is created with "every accounting figure at rest: ... `lot_variance` 0" while §3.7 says the figure "stays null until the lot is returned", and no sentence covers an `ISSUED` lot. Both readings are PRD-faithful, so the value is not uniquely derivable; the four covered counter assertions (`voted_quantity`, `spoiled_quantity`, `returned_unused_quantity`, `accounted_quantity` = 0) were kept. Scaffold rule that generated it: `Corner/entities/en_ballot_lot_retrieval_returns_stored_accounting_line`.

## Fixes to `test_helpers/`
- `assertions.py` — added `assert_same_instant(actual, expected, label)`: compares two ISO 8601 UTC instants as moments rather than byte strings. PRD §2.4 pins the exactly-three-fractional-digit rendering for `created_at`/`updated_at` (and `api_request_timestamp`) only; for logical-clock-read fields (`started_at`, `last_reconciled_at`) and echoed client-supplied instants (`press_window_start/end`, `scheduled_start/end`) the rendering is not derivable. The suite was itself inconsistent here — `test_priority_pair_validation.py` hard-codes `2026-09-01T14:00:00.000Z` for `started_at` while `test_boundary_precision_check.py` expected `2026-09-01T14:00:00Z` for the same field — which confirms the rendering was never PRD-pinned.

## Fixes to `test_suite/`
- `test_boundary_precision_check.py` — 3 tests (`..._notice_lead_exactly_at_the_requirement...`, `..._notice_lead_one_minute_over...`, `..._reconcile_persists_the_out_of_balance_reading`): moved `started_at` / `last_reconciled_at` out of the exact-string `assert_fields_equal` block into `assert_same_instant`. Every other asserted figure (2880/2881 lead minutes, variance 100, `OUT_OF_BALANCE`, version +1) is unchanged.
- `test_resource_temporal_overlap.py` — 5 tests: the same treatment for the 7 echoed `press_window_*` / `scheduled_*` comparisons. The half-open-adjacency and buffered-closed-conflict assertions themselves are untouched.
- `test_priority_pair_validation.py` — 2 tests: dropped `expected_status=201` on `POST /la-test-sessions/{id}/observers`. Observer sign-in creates no resource (PRD §3.8: the name "is appended to `observer_names`... and `observer_count` is recomputed as that array's length"), so PRD §4's "every other successful call answers 200 OK" applies; all nine other `add_observer` call sites in the suite, including `fixtures.sign_in_observers`, already expected 200 — this was an internal test inconsistency.

## Fixes to `implementation/`
- `routes_election.py::reconcile` — replaced `store.setf(...)` (which bumps `version` only when a field actually moves) with a direct field update plus an unconditional `store.touch()`. A repeat reconciliation writing byte-identical figures was leaving `version` unmoved, contradicting PRD §3.9: "`version` is bumped — which is why a client re-reconciling must read the election again to obtain a fresh `expected_election_version`."
- `routes_print.py::list_lots` — sort key changed from `created_at` to `(lot_code, created_at, _seq)`, per PRD §2.3: "Ballot lot lists are ordered by `lot_code` ascending, then by `created_at` ascending." (Checked every other list route: precincts/tabulators/candidates/custody-events already used their declared domain ordering.)
- `derive.py::void_lot` — the appended `VOID` custody event now records `actor_user_id` `"system"` instead of the triggering user. A lot is only ever voided by a cascade (rejected print job via contest withdrawal or style supersession), and PRD §2.1 states: "Custody events generated by a cascade rather than by a direct call record `actor_user_id` as the literal string `"system"`."

No PRD-required implementation check was removed or weakened, no skip/xfail was added, no error-id assertion was downgraded, and storage remains in-memory only with nothing seeded at boot.

**Orchestrator verification (per memory: a Step 7 agent can claim a clean sweep with no artifacts):** independently re-read all 8 `results.$i.json` (timestamps 22:22, ~63.9 KB each). Every round reports `passed=214 / total=214 / failed=0`. Clean sweep confirmed on disk.

## Step 8: Finalize PRD — 2026-09-03T22:35:00.000Z

`PRD_FINALIZED.md` is written and complete (ends at the §5 error-code table, the same terminal boundary as `PRD.md`; all 29 headings preserved).

## Line counts
- `PRD.md`: 540 lines
- `PRD_FINALIZED.md`: 544 lines (+4 lines, **+0.74%**) — 6 edits, 4 of them in-place sentence revisions, 2 new paragraphs.

## Changes
- **§2.1** — revise — cascade-generated custody events: named the three cascade lines that record `actor_user_id` `"system"` (`VOID`, `SEAL_BROKEN`, poll-close `RETURN`) and pinned that `actor_role` is *not* replaced but keeps the triggering caller's role — `derive.py:224-226`, `derive.py:323-325`, `routes_election.py:124-126`
- **§2.3** — insert — every computed ordering falls back to server insertion order once all declared keys tie — `routes_print.py:316`, `store.py:61-63`
- **§2.4** — insert — every returned instant, clock-read or client-supplied, is rendered ISO 8601 UTC with exactly three fractional digits; client instants are parsed and re-rendered canonically (offsets shifted to UTC) before storage, so echoes are moment-equal but not byte-equal — `util.py:35-41`, `routes_print.py:118-119`, `routes_tab.py:259-261`
- **§3.7** — revise — `lot_variance` "stays **null** until the lot is returned" -> stays at the `0` it was created with through `IN_TRANSIT`/`RECEIVED`/`ISSUED`/`VOIDED`; the return is its only writer — `routes_print.py:271`, `routes_print.py:433`
- **§3.8** — revise — observer sign-in mints no resource, answers `200 OK` with the updated session — `routes_tab.py:306-319`
- **§3.9** — revise — every accepted reconciliation bumps `version` unconditionally, including a repeat pass writing identical figures — `routes_election.py:153-164`

Not patched (PRD already uniquely determined the behavior, Step 7's change was an impl/fixture correction toward the PRD): the `list_lots` primary sort key (§2.3 already pins `lot_code` then `created_at`), and the `assert_same_instant` helper addition itself (a test-side artifact of the §2.4 silence, now closed).

## Per-edit pre-edit search log

**§2.1 (a)** actor attribution on custody events. **(b)** grepped all 12 `append_custody` callsites: cascade sites `derive.py:224` (`void_lot`, reached from `reject_job` <- `cascade_contest_withdrawn` and `cascade_style_superseded`), `derive.py:323` (`cascade_la_failure`), `routes_election.py:124` (close-polls); direct sites `routes_print.py:274/339/375/401/435` and `routes_tab.py:143/170/203`; read `append_custody` signature `derive.py:15-32`. All three cascade sites pass the triggering caller's `role` and the literal `"system"`; all direct sites pass real role + real user. **(c)** Scoped the `actor_role` claim to "those lines" only, so the direct-call sites are untouched; enumerated the three cascade line types explicitly rather than writing a general "system events" rule that could over-reach.

**§2.3 (a)** list ordering tiebreak. **(b)** grepped every `.sort(`/`sorted(` in `implementation/`: `store.order_key` (`store.py:61-63`) used by contests `routes_election.py:238`, jobs `routes_print.py:163`, decks `routes_style.py:170`, styles `routes_style.py:356`, sessions `routes_tab.py:301`; explicit keys at precincts `routes_style.py:69`, candidates `routes_style.py:184`-block, tabulators `routes_tab.py:80`, lots `routes_print.py:316`, custody events `routes_election.py:193`; internal passes `derive.py:78`, `calc.py:52-62` (`contest_sort_key`), `calc.py:71-85` (`candidate_sort_key`), `calc.py:161`, `calc.py:123`, `calc.py:232`. `_seq` is the terminal tiebreak in every one. **(c)** Widened from "these lists" to include "the internal sort passes of Section 3" since the same fallback governs the freeze/rotation/base-order passes; added the ledger example because custody events tie on `sequence_index` across subjects; added "insertion sequence is never itself a declared key".

**§2.4 (a)** rendering of instant-valued fields. **(b)** grepped `now_str|fmt_ts|parse_ts` and every `req_ts|opt_ts` callsite: `util.fmt_ts` (three digits always, `util.py:35-41`), `util.parse_ts` (accepts offsets, converts to naive UTC, `util.py:50-72`); writers `store.py:32/44`, `envelope.py:16`, `derive.py:17`, `routes_election.py:37/161/279/328`, `routes_print.py:118-119`, `routes_tab.py:201/259-261/357/387/414`. Every client instant (`election_date`, `filing_received_at`, `press_window_start/end`, `scheduled_start/end`, `public_notice_posted_at`, clock `now`) is re-rendered via `fmt_ts` before storage — none is stored raw. **(c)** Two softenings: added the explicit null carve-out (`fmt_ts(None)` returns `None`), and phrased the offset case as "comes back shifted to UTC" rather than claiming any particular offset syntax is echoed.

**§3.7 (a)** `lot_variance`'s value outside `RETURNED`. **(b)** `routes_print.py:271` (creation -> 0), `routes_print.py:433` (return-counts -> issued - accounted, only writer), `routes_print.py:395-399` (recall — does not touch it), `derive.py:212-227` (`void_lot` — does not touch it, and `RETURNED` lots are excluded from voiding by the `from_state` filter at `derive.py:214`), `serial.py:57-63` (always emitted), `calc.accountability` reads `accounted_quantity`, never `lot_variance`. **(c)** Enumerated the four non-returned states rather than writing "before return", and stated the recall/void non-interference explicitly. Left §3.6's "`lot_variance` 0" at creation verbatim — the contradiction resolves in its favor.

**§3.8 (a)** status code and response body of observer sign-in. **(b)** `routes_tab.py:306-319` (`envelope.ok` -> 200, returns `serial.session`); `envelope.ok`/`created` (`envelope.py:20-31`); grepped all 10 `envelope.created` callsites. **(c)** Deliberately kept the justification local to this endpoint instead of sharpening §4's general "creation endpoints answer 201" rule — `routes_print.py:284` (`deliver`) *does* create ballot lots yet answers 200, so any tightening of §4's universal wording would have manufactured a new mismatch there.

**§3.9 (a)** version movement on a repeat reconciliation. **(b)** `routes_election.py:152-165` (direct dict update + unconditional `store.touch`), `store.touch` (`store.py:43-46`, always bumps) vs `store.setf` (`store.py:49-58`, bumps only when a field moves) — `setf` is still used widely (e.g. `routes_style.py:89` assign-style, all `derive.py` recomputes), so a no-op write elsewhere does *not* bump. **(c)** Confined the "unconditional" claim to "every accepted reconciliation" and left §2.4's general "every mutation" rule verbatim.

## Step 9: Complete PRD — 2026-09-03T22:55:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as three sequential, file-partitioned passes over a single shared `PRD_COMPLETED.md` rather than one monolithic scan. Rationale: the implementation is 17 modules / ~3,055 lines and a single-pass scanner reliably under-covers it (a known failure mode is a PRD_COMPLETED.md that comes back byte-identical to its source, meaning the walk never happened). Passes were sequential, not concurrent, so they could not collide on Edit calls to the same file. Partition: A = cross-cutting core (app, util, errors, envelope, store, auth, validate, guards, serial, start.sh); B = computation/propagation (calc, derive); C = the four routes_*.py modules. Each pass received the prior passes' already-pinned list to prevent rework and double-patching.

### Pass A — core modules
- `PRD_FINALIZED.md` 544 lines / 106,813 chars -> `PRD_COMPLETED.md` 548 lines / 113,247 chars (+4 lines, +6,434 chars). 8 ambiguity-pins, 3 mismatch-revisions.
- §2 intro — insert — ambiguity — in-memory store never seeded, boot empties every collection and resets the clock to `2026-08-01T00:00:00Z`; listens on `PORT` (default 10000) bound to `0.0.0.0`; trailing slash equivalent — `app.py:20,57-59`, `store.py:20`, `start.sh:10`
- §2.1 — insert — ambiguity — `X-User-Role` consulted first, `X-Role` only when absent/empty; role match exact, case-sensitive, untrimmed; `X-User-ID` never authenticated, recorded null when absent — `auth.py:31-35,45-52`
- §2.2 `api_request_id` — insert — ambiguity — `req_` + exactly 20 chars from `A-Z0-9`, total length 24 — `util.py:84-88`
- §2.2 `api_request_timestamp` — revise — **mismatch** — envelope timestamp reads the **logical clock**, not host wall clock, so it repeats until the clock moves — `envelope.py:13-17`
- §2.2 `data` — insert — ambiguity — a resource object always carries its full declared field set, identical across 201/200/transition responses, no-value fields present as null — `serial.py:93-94`
- §2.3 — insert — ambiguity — `limit`/`offset` must be integer literals; out-of-range/negative/non-integer -> `ERR_INVALID_REQUEST` (rank 30), never clamped; omitted or empty-string take defaults; offset past `total_count` returns empty `data` with full `total_count`, `has_more` false; enum filters reject unknown values, id filters opaque exact-match (never 404), empty-string and undeclared params ignored — `validate.py:154-190`, `envelope.py:33-44`
- §2.4 version paragraph — revise — **mismatch** — a mutation is a write that actually moves a stored field: cascade recomputation reproducing the stored figure bumps neither `updated_at` nor `version`; direct workflow writes bump unconditionally — `store.py:43-58`
- §2.4 timestamp paragraph — insert — ambiguity — full accepted parse grammar (`T`/`t`/space, optional `:SS`, 1-9 fractional digits, optional `Z`/`z`/`±HH:MM`/`±HHMM`), whitespace stripped, missing zone read as UTC, non-string/date-only/calendar-impossible rejected, sub-millisecond digits **truncated** not rounded — `util.py:44-72,35-41`
- §2.6 — insert — ambiguity — optional field explicitly `null` = absent and takes its default; no cross-type coercion; enum/role/format comparisons exact and case-sensitive; strings never trimmed, empty/whitespace-only valid; de-duplicated arrays keep first-occurrence order, vocabulary check precedes must-contain; absent/empty/`null` body = empty object, non-object or unparseable body = `ERR_INVALID_REQUEST` 400, `Content-Type` never consulted — `validate.py:14-25,28-30,50-66,69-94,111-129`
- §4 layout row — revise — **mismatch** — `basis` defaults to `CERTIFIED_BASIS`, resolving the PRD's own §3.2-vs-§4 contradiction in favour of impl — `routes_style.py:178`
- §5 intro — insert — ambiguity — three non-catalog identifiers: unrouted path -> 404 `ERR_NOT_FOUND`, disallowed method -> 405 `ERR_METHOD_NOT_ALLOWED`, unhandled fault -> 500 `ERR_INTERNAL`, all in the standard error envelope — `app.py:33-54`
- Verified already-pinned: all 49 error ids + statuses match `errors.py` one-for-one (programmatic diff); all 13 serializer field tuples use names §2.11/§3 already name; pagination defaults 10/1/100/0; rank ordering auth -> schema -> path -> phase -> state; §2.9 rounding disciplines; `store.order_key = (created_at, _seq)` insertion tiebreak.

### Pass B — calc.py + derive.py
- 548 lines -> 548 lines (all in-paragraph); 113,247 -> 115,425 chars (+2,178). 5 ambiguity-pins, 2 mismatch-revisions.
- §2.10 — insert — ambiguity — a row written more than once by the propagation bumps `version` once *per* moving write; the election row carries five separately written derived groups, so one call can advance `version` by more than one — matters for `expected_election_version` — `derive.py:172-181`, `routes_print.py:378-379`
- §2.11 — revise — **mismatch** — `sequence_index` is allocated as `len(events_of_subject)+1` at append time and never renumbered (was defined as position ordered by `occurred_at`/`created_at`), so a line appended after a clock rewind still takes the higher index — `derive.py:18`
- §2.11 — insert — ambiguity — `from_state` is null on the `TRANSFER_OUT` line of a newly created lot — `derive.py:15-32`, `routes_print.py:275`
- §2.11 — revise — **mismatch** — seal uniqueness is over the `seal_number` currently stored on any lot/tabulator of the election regardless of custody state (a `VOIDED` lot keeps and keeps blocking its seal); a broken seal is cleared to null and frees the number; the addressed row is excluded from its own check; a null seal never collides — `derive.py:35-48,216-220`
- §3.5 hop 1 — insert — ambiguity — the withdrawn contest's own candidates are untouched, keeping `CERTIFIED` and `base_order_index` — `derive.py:249-268`
- §3.5 hop 3 — insert — ambiguity — a rejected job's `invoice_basis` is left as it stood while the four money fields go to 0 — `derive.py:230-239`
- §3.8 — insert — ambiguity — repeated `(contest_id, candidate_id)` pairs are legal in both `expected_marks` and `reported_marks`, and their `mark_count`s are summed per key before comparison — `calc.py:222-233`
- §3.8 L&A-failure hop 2 — insert — ambiguity — `la_session_count` is not rewritten by a failure; only a passing result recomputes it — `derive.py:318-330`, `routes_tab.py:393-395`
- Verified already-pinned: contest sort key; both candidate order methods and tiebreaks; both basis filters; all four rotation-offset branches incl. degeneracies and `printed_position = ((base+g) mod n)+1`; `required_ballot_quantity` ceil-11/10; three freight tiers with inclusive edges; estimate sum-then-round vs final per-lot round-then-sum; the whole accountability worksheet incl. both floor divisions and the positive-only net-variance asymmetry; absolute-deviation discrepancy; readiness predicates; vendor `active_job_count` and rolling `quality_defect_rate_bp`; `rotation_seed_index` re-ranking; `style_contest_count`; supersession's four consequences; L&A-failure custody-axis revert.

### Pass C — the four routes modules (58 handlers walked)
- 548 lines -> 548 lines (all in-paragraph); 115,425 -> 119,001 chars (+3,576). 14 ambiguity-pins, 5 mismatch-revisions.
- §1 clock — revise — ambiguity — answers `200 OK` with `data` an object carrying exactly one field `now`; the role header is never examined, so absent/bogus roles are accepted — `routes_tab.py:409-414`
- §2.3 — revise — ambiguity — precinct list key is `precinct_code` then `created_at` — `routes_style.py:69`
- §2.3 — revise — ambiguity — tabulator list key is `asset_tag` then `created_at` — `routes_tab.py:80`
- §2.6 — insert — **mismatch** — the body-parse rules bind only payload-declaring operations; the seven bodyless writes never inspect the body and accept non-JSON bytes — `routes_election.py:64,80,106,118,251`, `routes_style.py:237`, `routes_tab.py:322`
- §3.2 layout read — insert — ambiguity — `contests` ordered by `ballot_order_index` (nulls last) then the §3.1 contest sort key; per-contest field set pinned incl. `rotation_offset`/`rotation_modulus`, both `0` for an empty roster — `routes_style.py:184-203`
- §3.3 — revise — ambiguity — `precinct_code` uniqueness is convention, not an enforced check — `routes_style.py:23-45`
- §3.3 — revise — ambiguity — `style_code` uniqueness likewise unenforced — `routes_style.py:104-145`
- §3.3 assign-style — insert — ambiguity — the *displaced* style's `precinct_count` is recomputed too — `routes_style.py:90-94`
- §3.4 — insert — ambiguity — both arrays required non-empty de-duplicated strings; `certified_formats` restricted to the five formats, `translated_languages` unrestricted — `routes_style.py:221-223`
- §3.4 proof decision — insert — **mismatch** — SoD fires only when the caller presents an `X-User-ID`; a null user is never refused even against a null `proof_requested_by_user_id` — `routes_style.py:278`
- §3.4 lock-styles — insert — ambiguity — an election with zero precincts satisfies both preconditions vacuously and advances with no style locked — `routes_election.py:84-101`
- §3.6 deliver — insert — ambiguity — vendor-ownership `ERR_UNAUTHORIZED` is not the rank-20 role check: it runs after manifest schema and after the job's not-found error; a rep with no `X-User-ID` is refused — `routes_print.py:243-244`
- §3.7 receive — revise — ambiguity — `quantity_received` is never compared to `quantity_shipped`; short and over counts are both stored as counted — `routes_print.py:326,336`
- §3.8 unit intake — revise — ambiguity — `asset_tag` uniqueness unenforced — `routes_tab.py:29-50`
- §3.8 test deck — revise — ambiguity — `deck_code` uniqueness unenforced — `routes_style.py:297-344`
- §3.8 start — insert — **mismatch** — programmer-vs-conductor SoD fires only on a caller presenting `X-User-ID` — `routes_tab.py:335`
- §3.8 record results — revise — **mismatch** — reported `mark_count` may be `0` (deck marks must be >=1), the array may be empty, and reported pairs are not validated against the style — `routes_tab.py:368`, `validate.py:145`
- §3.8 passing branch — insert — ambiguity — a deck voided from outside mid-session stays `VOIDED` rather than becoming `CONSUMED` — `routes_tab.py:391-392`
- §4 table — revise — **mismatch** — lock-styles row now says "every APPROVED ballot style *that some precinct points at*" — `routes_election.py:89-100`
- Verified already-pinned: all 58 rows' role lists match `auth.require(...)` exactly; every §2.5 phase-table row matches its `require_phase` tuple incl. the 7 ungated writes; every list route's filter set; the `approve-proof` and `proof-decision` guard orders. `deploy_election`'s pre-check re-derivation, `return-counts` not re-running the readiness chain, and `create_job`'s vacuous cross-election clause were left unpinned because they are unobservable through the API.

### Totals across the three passes
27 ambiguity-pins + 10 mismatch-revisions = 37 edits. `PRD.md` 540 lines / 104,425 chars -> `PRD_FINALIZED.md` 544 / 106,813 -> `PRD_COMPLETED.md` 548 lines / 119,001 chars (+8 lines and +14,576 chars over PRD.md, +13.96% by size).

**Orchestrator verification:** independently confirmed `PRD_COMPLETED.md` differs from `PRD_FINALIZED.md` (72 changed diff lines — the scan genuinely ran and did not return a byte-identical copy), 29 headings intact, and the file ends on the complete final row of the §5 error table (`| ERR_LOT_ACCOUNTING_EXCEEDS_RECEIPT | 409 |`). Step 9 touched only PRD_COMPLETED.md; `implementation/`, `test_suite/` and `test_helpers/` are unchanged since the clean 8/8 sweep, so the 214/214 result still stands. **Pipeline complete.**
