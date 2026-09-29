# Worklog — task_2622_airline_passenger_rights_refund_compliance

## Step 1: Create task directory — 2026-09-03T20:56:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2622_airline_passenger_rights_refund_compliance` and `.../workspace` (pre-assigned path; no index scan performed).

## Step 2: Generate scaffold — 2026-09-03T22:40:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2622_airline_passenger_rights_refund_compliance/`)

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 2966 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1520 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5058 |

Directory also contains the pre-existing `worklog.md` and empty `workspace/`.

**Linter verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2622_airline_passenger_rights_refund_compliance/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2622_airline_passenger_rights_refund_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2622_airline_passenger_rights_refund_compliance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     106
  Calls scanned (§1.8+§1.9):  904

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold contents**
- 12 entities, 50 endpoints (19 reads / 31 writes), 8 state machines, 16 calculations, 40 validation priorities, 59 error codes, 5 roles, 2 `concurrency_rules`.
- `complexity_profile`: `difficulty_level: expert_plus`, `entity_topology: flat`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency]`.
- §1.8: 22 difficulty instances. §1.9: 126 corner instances — 106 with full test recipes plus 20 `excluded_because` stubs, spread across all nine claim-guide sections (entities 22, state_machines 28, calculations 15, validations 33, endpoints 6, errors 5, rbac 9, cross_cutting 7, consistency_model 1).

**Final-pass fixes this session**
- Corrected the malformed `excluded_because.difficulty_instance` on `refund_obligation_cross_reference_integrity_segment_from_another_booking` to the bare §1.8 instance name; all 20 stub targets now resolve.
- Closed the last three uncovered error codes: added an eighth sentinel 404 call (`ERR_CONSUMER_COMPLAINT_NOT_FOUND`) to `every_remaining_entity_resolves_its_own_not_found_code`, and authored two new `section: errors` instances — `finalize_on_already_finalized_denied_boarding_record_rejected` (statutory ladder `min(round_half_up(45000×2.0)=90000, 77500) = 77500`, second finalize → 409, exactly one DENIED_BOARDING obligation, ledger stays 77500) and `file_report_on_still_active_tarmac_event_then_on_terminal_event_rejected` (same code guards both ends of the fork-join: file-report while DELAY_ACTIVE, then claim-exemption on terminal REPORT_FILED, with the segment pre-set to DEPARTED so the priority-47 guard can't be the cause). Error-code coverage is now 59/59.

**Notable design decisions**
- Refund obligations are minted both proactively (cascade from cancellation, `created_by_user_id = null`) and on request, with a booking-level `booking_refund_headroom` ledger: PROACTIVE clamps to headroom, REQUEST_BASED is rejected (`ERR_REFUND_EXCEEDS_HEADROOM`) rather than clamped — the dual-variant calculation's `variant_delta_cents = proactive − request_based`.
- Denied-boarding compensation is a tiered ladder whose *effective* category is recomputed at finalize: a VOLUNTARY record lacking oversale confirmation or written disclosure is demoted to `RECATEGORIZED`/INVOLUNTARY with a divergent side-effect set (different variant, statutory amount, no disclosure-floor check).
- Segregation of duties is enforced per user id (creating officer cannot initiate settlement; initiating officer cannot complete it) at priority 50, which required recipes to arrange a manually created obligation on a DISRUPTED_UNUSED segment so priority 45 does not pre-empt the 403.
- Deadline semantics are strict-`>` throughout (tarmac 180/240 min, bag 12/30 h, ack 30 d, answer 60 d, election 5 d, auto-close 30 d), and boundary instances assert both the exact-instant (no breach) and instant+1s (breach) cases via the logical clock `POST /_clock/set_current_utc`.
- Optimistic concurrency is expressed as two §1.2.1 rules with distinct 412 codes (`ERR_STALE_BOOKING_VERSION` on obligation create, `ERR_STALE_POLICY_VERSION` on report create), with a dedicated instance walking `Booking.version` 1→4 to prove child creates bump the parent.

## Step 3: Copy shared files — 2026-09-03T22:40:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T22:58:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **419 lines / 108,568 bytes**, written in 12 incremental heredoc appends (no single giant Write, no truncation). File ends cleanly on the final row of the §5 error table; no audit footer, no contract report, no meta-commentary inside the document.

**Section list**
- `# Airline Passenger Rights & Refund Compliance API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Compliance Office Roles and Caller Identity; 2.2 API Response Structure (byte-identical copy of the canonical fixed block); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Row Versions; 2.5 Request Validation Precedence; 2.6 Ledger-Parent Version Guards; 2.7 Money, Minutes and Boundary Conventions; 2.8 The Logical Compliance Clock; 2.9 The Policy Profile as the Tunable Rulebook; 2.10 Segregation of Duties on the Money Chain; 2.11 Conserved Ledgers and Cascade Discipline (11 subsections)
- `## 3. Business Logic & Workflows` — 3.1 Building the Compliance Record; 3.2 Declaring Disruption and the Cancellation Cascade; 3.3 Paid Extras: Ancillary Services and Checked Baggage; 3.4 Denied Boarding: Categories, the Statutory Ladder and Informed Consent; 3.5 Tarmac Delay Occupation, Deplaning Deadlines and Contingency Reporting; 3.6 Minting a Refund Obligation: Valuation, Headroom and Deadlines; 3.7 Two Axes: Electing the Instrument and Moving the Money; 3.8 Consumer Complaints, Disability Matters and the Activity Trail; 3.9 The Compliance Sweep and Regulator Filings (9 subsections)
- `## 4. Endpoint Definitions` (4 columns: Method, Path, Description, Authorized Role(s))
- `## 5. Error Code Catalogue` (2 columns: Error ID, HTTP Status Code) — **last section**

**Coverage confirmation**
- Endpoints: scaffold declares 50 method+path pairs; §4 table has exactly **50 rows**, 0 missing (45 distinct paths, 5 carrying both GET and POST).
- Errors: §5 has exactly **59 rows**; 59 distinct `ERR_` identifiers; 0 missing. Statuses cross-checked against every `http_status` in the scaffold.

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** 209 snake_case identifiers extracted from the scaffold; all 209 appear verbatim in backticks; 0 missing.
- **Contract 2 — Rule Coverage: PASS.** All 40 validation priorities rendered as the ordered ladder in §2.5; both OCC rules in §2.6; all 8 state machines and every transition across §3.2–§3.9; all 16 calculations with pinned operation orders; every cross-entity side effect (6-link cancellation cascade, 3-link baggage cascade, 3-link answer chain, void compensations, sweep phases); all `applies_to` scopes; every field-level default (including all 14 PolicyProfile defaults); sibling-branch symmetry (DEPLANED vs EXEMPTION_INVOKED, FINALIZED vs RECATEGORIZED, SUCCEEDED vs FAILED, CASH vs TRAVEL_CREDIT). 186/220 UPPER_SNAKE scaffold tokens present; the 34 absent are prose-emphasis words, scaffold abbreviations, and the 9 tuning-constant identifiers rendered as literal values in prose (all values verified present).
- **Contract 3 — §3 Path Purity: PASS.** Lines 160–297 contain zero backticked `/`-tokens, zero HTTP verbs, zero `compliance/` substrings.

Also verified absent: pseudocode operators, fuzzy quantifiers, scaffold section numbers, difficulty tiers. The two withheld design files were never opened.

**Orchestrator truncation check:** independently ran `wc -l` (419) and `tail -c 900` — file ends on a complete `| ERR_FAILURE_REASON_REQUIRED | 422 |` table row at the end of §5, the document's final section. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T02:35:00.000Z

The suite is complete. Final state for `task_2622_airline_passenger_rights_refund_compliance`:

## Output (both dirs at the TASK ROOT — nothing under `workspace/`)

`test_helpers/` (9 files, 2,630 lines): `__init__.py` 103, `api_client.py` 511, `api_errors.py` 168, `assertions.py` 369, `constants.py` 204, `factories.py` 452, `fixtures.py` 480, `test_users.py` 81, `types.py` 262.

`test_suite/` (19 files, 8,965 lines): `conftest.py` 21; queue A `test_01` 258, `test_02` 400, `test_03` 340, `test_04` 261, `test_05` 397, `test_06` 285, `test_07` 398, `test_08` 204, `test_09` 243; queue B `test_10_entities` 806, `test_11_state_machines` 1074, `test_12_calculations` 644, `test_13_validations` 1289, `test_14_endpoints` 534, `test_15_errors` 395, `test_16_rbac` 693, `test_17_cross_cutting` 550, `test_18_consistency` 173.

## Coverage — 175 tests, zero gaps
- **Queue A (Difficulty): 46 tests / 22 instances**, every instance >= 2 tests.
- **Queue B (Corner): 129 tests / 106 non-stub instances**, every instance >= 1 test, all nine sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).
- **No instance was skipped.** All 128 non-stub instances are translated; the 20 `excluded_because:` stubs are not. Where a design recipe asserted something the PRD does not uniquely derive, only that assertion was dropped (test still emitted): validations [4]/[6]/[9] null-field and profile-flag claims; errors [3] booking `version == 3` -> before/after "unchanged" comparison; cross_cutting [3] the recipe's `travel_credit_default_permitted is true` claim (PRD §2.9 defaults it to **false**); cross_cutting [4] the recipe's "`open_complaint_count` was 1 before the close" claim (PRD §3.2 counts only RECEIVED/ACKNOWLEDGED/INFO_REQUESTED, so an ANSWERED complaint is already 0 — asserted 0). Also corrected recipe enum typos throughout (`EQUIPMENT_FAILURE`->`EQUIPMENT_SWAP`, prose exemption reason->`ATC_DIRECTIVE`, `WEB_FORM`->`WEB`).

## Verification run
- `python3 -m py_compile` clean on all 28 generated .py files; `python3 -m pyflakes` clean on all of `test_suite/`.
- `pytest --collect-only` -> **175 tests collected**.
- Automated audit: every test has a docstring with **exactly one** `Design:` line as its last line, every tag resolves to a real non-stub instance (0 bogus), every test carries >=1 PRD citation, and **all 175 tests' citations are byte-verbatim** against `workspace/PRD.md` after whitespace normalisation; no docstring or comment mentions "scaffold".

## Two systemic bugs found and fixed this session
1. **`validate_success(...)["data"]` — 39 sites across 9 files.** The framework's `validate_success` already returns `body["data"]`, so every one of these would have raised `KeyError: 'data'` at runtime. All stripped.
2. **`build_world(api)` creates no flight segments** unless `segment_fares=[...]` is passed. Four helpers indexed `world.segments[0]` after a bare call (`test_14:250`, `test_15:187`, `test_15:298`, `test_16:109`) and would have raised `IndexError`; all now pass `segment_fares=[50000]`.
3. One non-verbatim citation in `test_11_state_machines.py:177` was replaced with the exact PRD text.

`workspace/implementation/` was never created, read, or modified.

**Orchestrator note (process deviation):** Steps 5 and 6 were launched in two consecutive messages rather than a single message, so they overlapped in time but Step 6 started ~15s after Step 5. Physical isolation of the impl generator from `test_suite/` was therefore not guaranteed by directory non-existence alone; it was enforced instead by an explicit absolute prohibition in the Step 6 prompt against reading `test_helpers/`, `test_suite/`, and both design YAMLs. Step 6's own report confirms its only inputs were INSTRUCTION.md, SCAFFOLD.yaml, PRD.md.

## Step 6: Generate implementation — 2026-09-04T02:10:00.000Z

The implementation is complete, compiles, and boots clean with an empty store.

## Files — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` (exec, +x) | 9 | guarded `if ! python3 -c "import flask"` install, then `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 68 | blueprint registration, `ApiError`/`HTTPException`/catch-all handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 137 | in-memory dicts, logical clock, `_seq` monotonic ordering, ISO-8601 formatters |
| `errors.py` | 82 | all 59 error ids -> HTTP status |
| `envelope.py` | 49 | `meta`/`response_type`/`data` envelope + pagination meta |
| `auth.py` | 72 | `X-User-ID`/`X-User-Role`, 5 roles, ownership-before-existence |
| `validation.py` | 208 | shape ladder, pagination bounds, path/body existence |
| `calc.py` | 254 | 16 calculations, `Decimal`+`ROUND_HALF_UP`, statutory constants |
| `ledger.py` | 251 | booking/passenger rollups, the single `mint_obligation` headroom path, activity trail |
| `routes_core.py` | 272 | profiles, passengers, bookings, sub-lists, refund-exposure, `/_clock/set_current_utc` |
| `routes_segments.py` | 304 | segments, declare-disruption + cancellation cascade, record-operation |
| `routes_extras.py` | 234 | ancillary purchases, checked bags |
| `routes_denied.py` | 161 | denied-boarding records + statutory ladder finalize |
| `routes_tarmac.py` | 177 | occupations, deplane, claim-exemption, file-report |
| `routes_obligations.py` | 395 | create/elect/initiate/complete/void + lists |
| `routes_complaints.py` | 264 | file/ack/request-info/answer/reopen + activities |
| `routes_reports.py` | 352 | regulator reports + the five-phase sweep |

**Endpoints: exactly 50 (19 GET, 31 POST)** — verified from Flask's url_map, matching the §4 table. Storage is pure Python dicts; nothing is seeded, no file/SQLite/tmp state.

## Verification
`py_compile` clean on all 16 modules. Two smoke runs on port 18622 exercised the cancellation cascade -> FARE obligation -> credit election (bonus 9000 on 90000) -> SoD-blocked initiate/complete -> settle -> passenger credit 99000; tarmac 270 min vs 240 deadline -> violation; recategorized denied boarding (80000 statutory, no disclosure); disability complaint deadlines; a sweep (`deadline_breach=1, auto_default=1, answer_breach=1, open_violations=3`) proven **idempotent** on re-run; ancillary/bag obligations with void compensations; error envelopes for 401/403/404/409/412/422 and pagination meta. Servers were killed by exact PID resolved from `ss -ltnp` on the specific port (2875932, 2909394) — no pattern kill was used. A final fresh boot on 18623 returned an empty booking list, confirming no carry-over state.

## PRD ambiguities resolved (PRD wins over SCAFFOLD)
- **Duplicate vs referential order**: §2.5 step 15 puts `ERR_DUPLICATE_OBLIGATION_FOR_SOURCE` *before* step 16's `ERR_SEGMENT_BOOKING_MISMATCH`/`ERR_BASIS_REFERENCE_MISMATCH`, contradicting the §3.6 narrative order. Followed §2.5; duplicate is checked on the basis-matched source field, skipped when that field is absent.
- **Failed settlement**: §3.7 states the booking version advance only on `SUCCEEDED`. No booking recompute/version bump on `FAILED`.
- **`DEADLINE_BREACH_FLAGGED` activity rows**: appended, one row per *newly* set flag (`ack_due_utc` / `answer_due_utc`), `actor_role` literal `system`, so re-running the sweep adds nothing.
- **Sweep version discipline**: phases 1+2 can touch one obligation twice; rows are collected dirty and `touch`ed once per request per §2.4. Breach flags are set-only (monotone), never cleared.
- **Already-voided obligation** -> `ERR_OBLIGATION_NOT_VOIDABLE` (PRD explicit), while `INITIATED` -> `ERR_OBLIGATION_STATE_INVALID`.
- **`request_received_utc`** accepted as optional on obligation create; used only as the fallback start instant when the basis-derived instant is null, else the logical clock.
- **`obligation_start_utc` for ANCILLARY** needed the mark-not-provided instant, which no entity field holds — stored on the purchase as a non-serialized internal `_occurred_at_utc` (cleared on a `CREATED_IN_ERROR` void).
- **Direct `GOODWILL_GRANT` create** has no complaint reference, so gross entitlement is 0 under `GOODWILL_GRANT_AMOUNT`.
- **On-time bag delivery** does not advance `Booking.version`.
- **`is_international`, `oversale_confirmed`, `written_disclosure_provided`** treated as optional bodies with §3.1/§3.4 defaults; `ERR_INVALID_REQUEST` is always 400.

## Step 7: Test/fix iteration — 2026-09-04T01:20:00.000Z

Two parallel 8-round stability sweeps (`--isolation per-test-server`, 175 tests/round, ~330s/round).

| sweep | result |
|---|---|
| 1 | 172/175 in **all 8** rounds — the same 3 failures every round, zero flakiness |
| 2 | **175/175 in all 8 rounds** |

### Failure 1+2 — `test_04_transitive_cascade.py::TestLateBagDeliveryCascade` (both tests)
`Setup step failed with HTTP 400: ERR_INVALID_REQUEST - tag_number must be exactly 10 characters.`
The `_late_bag` helper passed `tag_number="ZQ0099001"` — **9** characters. PRD §2.5 ("`tag_number` is exactly ten characters") and §3.3 ("a `tag_number` of exactly ten characters") both require ten, so the implementation's rejection was correct and the fixture payload was the defect. Fixed to `"ZQ00990010"` (STEP 2: factory built a PRD-violating precondition). Audited every other hardcoded `tag_number=` in `test_suite/` and `test_helpers/` — all already exactly 10.

### Failure 3 — `test_11_state_machines.py::TestComplaintWorkflowTransitions::test_granting_a_refund_in_the_answer_mints_a_goodwill_obligation`
`expected disruption_posture REFUND_OBLIGATED, got NORMAL`
The test's world is `build_world(api, total_fare_cents=50000)` with **no `segment_fares`**, i.e. a booking with zero flight segments. PRD §2.11 pins the resolution order: *"it is `NORMAL` when the booking has no segments at all; otherwise, if the booking has at least one non-voided obligation, it is `CLOSED_OUT` … and `REFUND_OBLIGATED` when at least one is not; …"* — the obligation branch is only reached **otherwise**, so a segmentless booking recomputes to `NORMAL` no matter how many live obligations it carries. Note also that §3.8 link three says only that `disruption_posture` "is recomputed", deliberately *without* the "which reaches `REFUND_OBLIGATED`" parenthetical that §3.2 link four and §3.3 link three do carry. `ledger.py::recompute_booking` implements §2.11's ladder verbatim, so the implementation was right and the assertion mis-translated PRD.

Fixed in `test_suite/` (assertion layer): expected posture corrected to `NORMAL`, `segment_count=0` added to make the governing precondition explicit, and the §2.11 sentence added verbatim to the docstring. The assertion remains an exact-value check — no downgrade, no skip.

### Not changed
`workspace/implementation/` required **no** edits: every one of the three failures traced to the test artifact. No test was deleted; PRD verbatim-covers and uniquely determines all 175 assertions as they now stand.

### Step 7 — returned summary (verbatim, orchestrator-pasted) — 2026-09-04T01:13:00.000Z

Clean 8-round sweep achieved. Final state: **175/175 passing in all 8 parallel rounds.**

## Summary

**Iterations run: 2**

Sweep 1: 172/175 in all 8 rounds — the same 3 failures in every round (deterministic, zero flakiness).
Sweep 2: **175/175 in all 8 rounds** (~330s/round).

**Tests deleted: none.** All three failures traced to the test artifact, and in each case PRD verbatim-covers and uniquely determines the rule — so the fix was to make the test faithful, not to remove it.

**Fixes applied to `test_suite/` (no `test_helpers/` changes were needed):**

1. `test_suite/test_04_transitive_cascade.py` — `_late_bag()` helper passed `tag_number="ZQ0099001"`, which is **9** characters. PRD §2.5 ("`tag_number` is exactly ten characters") and §3.3 ("a `tag_number` of exactly ten characters") both mandate ten, so the implementation's `ERR_INVALID_REQUEST` was correct and the payload was the defect. Changed to `"ZQ00990010"`. This fixed both `TestLateBagDeliveryCascade` tests, which shared the helper. I audited every other hardcoded `tag_number=` across `test_suite/` and `test_helpers/` — all were already exactly 10.

2. `test_suite/test_11_state_machines.py` — `test_granting_a_refund_in_the_answer_mints_a_goodwill_obligation` asserted `disruption_posture == "REFUND_OBLIGATED"`, but its world is `build_world(api, total_fare_cents=50000)` with no `segment_fares`, i.e. a booking with **zero flight segments**. PRD §2.11 pins the resolution order: *"it is `NORMAL` when the booking has no segments at all; otherwise, if the booking has at least one non-voided obligation, it is `CLOSED_OUT` … and `REFUND_OBLIGATED` when at least one is not"* — the obligation branch is only reached "otherwise". Corroborating detail: §3.8 link three says only that `disruption_posture` "is recomputed", deliberately omitting the "which reaches `REFUND_OBLIGATED`" parenthetical that §3.2 link four and §3.3 link three both carry. Corrected the expectation to `NORMAL`, added `segment_count=0` to make the governing precondition explicit, and added the §2.11 sentence verbatim to the docstring. Still an exact-value assertion — no downgrade to a status check, no skip/xfail.

**Fixes applied to `implementation/`: none.** `ledger.py::recompute_booking` already implements §2.11's posture ladder verbatim (including the leading zero-segment clause), and `validation.py`'s ten-character `tag_number` check is PRD-required. Per the cardinal rules I did not weaken either check to accommodate the tests.

**Orchestrator verification (independent of the subagent):** `results.{1..8}.json` all present, each `passed=175 failed=0 total=175`; mtimes 01:03 UTC postdate the two test fixes (00:56 / 00:57 UTC), so the green sweep is the post-fix sweep, not a stale artifact.

## Step 8: Finalize PRD — 2026-09-04T01:22:00.000Z

`workspace/PRD_FINALIZED.md` created. It is byte-identical to `PRD.md` — zero edits were warranted.

## Line counts
- `PRD.md`: 419 lines; `PRD_FINALIZED.md`: 419 lines; delta 0 (0.00%). md5 matches (`ecd09b40…`), `diff` is empty.

## Changes
None. Both `<step_7_diff>` items were pure test-fixture defects at sites where `PRD.md` already uniquely determines the implementation's behavior.

## Per-item verification log

**Item 1 — `tag_number` length (test_04 `_late_bag()` 9-char tag)**
- (a) Subject: `tag_number` shape validation and every consumer of it.
- (b) Paths enumerated: `grep -n "tag_number" implementation/*.py` -> only three hits, all in `routes_extras.py` (`BAG_SPEC` at :121, the duplicate scan at :140, the persisted field at :146). `BAG_SPEC` declares `field("tag_number", "string", True, exact_len=10)`; `validation.py::_check_string` :69-70 enforces `len(value) != 10 -> ERR_INVALID_REQUEST` and applies **no** charset pattern, matching PRD §2.5/§3.3's "exactly ten characters" with no charset claim. `create_bag` (:128-159) then does the linear `ERR_DUPLICATE_TAG_NUMBER` scan §3.3 requires. Implementation is exactly what PRD mandates; the 9-char payload was the defect.
- (c) No wording adjustment — no edit.

**Item 2 — zero-segment `disruption_posture` (test_11 goodwill-grant expectation)**
- (a) Subject: resolution of `disruption_posture`, i.e. the §2.11 posture ladder and every place a posture value is written.
- (b) Paths enumerated: `ledger.py::recompute_booking` :41-52 is the **only** computing path, and it implements §2.11 verbatim and in order — `segment_count == 0 -> "NORMAL"`, `elif live: CLOSED_OUT/REFUND_OBLIGATED`, `elif any disruption_type != "NONE": DISRUPTED`, `else NORMAL`. Grepped all non-`ledger.py` occurrences of `posture`: only `routes_core.py:162` (booking-creation literal `"NORMAL"`, matching §3.1) and `routes_core.py:180` (the `disruption_posture` list filter of §2.3). Every cascade in `routes_segments.py`, `routes_extras.py`, `routes_denied.py`, `routes_obligations.py`, `routes_complaints.py` reaches posture only through `ledger.bump_booking`/`recompute_booking`, so no callsite can diverge from the ladder. §2.11's ordered ladder is the governing text and matches the code exactly. The failing test's world had zero segments, so `NORMAL` was already the PRD-determined answer.
- (c) No wording adjustment — no edit. Specifically considered softening the §3.3 link-three parenthetical for the hypothetical zero-segment-booking-with-a-late-bag path, but rejected it: §2.11 already pins the ladder unambiguously with explicit ordering, so no PRD silence or mismatch exists at the Step 7 site, and an inserted qualifier would be a manufactured edit.

Also re-checked that the two repaired test_04 late-bag tests pass against unmodified implementation with their exact-value assertions intact (fee face value 3500, `FEE_FACE_VALUE`, `PROACTIVE`, clock start `delivered_at_utc`, 7-day credit-card deadline, `collected_total_cents` 53500) — all already determined by PRD §3.3/§3.6.

**Orchestrator note:** a byte-identical PRD_FINALIZED.md is the expected outcome here — Step 7 applied 0 implementation fixes and 0 deletions, so its scope contained no PRD-silence site. Step 8 was still run (not skipped) because the skip condition requires 0 `test_suite/` fixes as well, and there were 2.

## Step 9: Complete PRD — 2026-09-04T01:50:00.000Z

Run as **three sequential file-partitioned passes** over `implementation/`, each editing the same `workspace/PRD_COMPLETED.md` in place. Rationale (orchestrator decision, made without user input per the non-interactive mandate): the implementation is 16 modules / ~3,000 lines, and a single-pass "walk implementation exhaustively" scan on an artifact this size reliably degenerates into a shallow read that produces a near-identical output file. Partitioning by module guarantees every module is actually walked, at the cost of three sequential subagent runs.

Partition: Pass A = app/store/errors/envelope/auth/validation/routes_core; Pass B = calc/ledger/routes_segments/routes_extras; Pass C = routes_denied/routes_tarmac/routes_obligations/routes_complaints/routes_reports.

### Pass A summary (verbatim)

PASS A complete. All edits are in-paragraph; no sections, paragraphs, or table rows were added.

**Line count:** 419 before -> 419 after (15 lines textually changed).
**Counts:** 14 ambiguity-pins, 1 mismatch-revision.

**Changes**

- §2.1 (roles/identity) — insert — ambiguity — a header value consisting only of whitespace counts as empty for `ERR_UNAUTHENTICATED` — `auth.py:29-32`
- §2.1 (ownership) — revise — **mismatch** — PRD listed the booking *collection* among the reads that raise `ERR_NOT_RESOURCE_OWNER`; impl never rejects there, it silently narrows the result set to the caller's own bookings before filters and paging (a `passenger_id` filter naming another passenger returns an empty page, `total_count` 0) — `routes_core.py:178-183`
- §2.2 (success envelope bullets) — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A-Z0-9` — `envelope.py:10-14`
- §2.3 (pagination) — insert — ambiguity — `limit`/`offset` must be canonical bare decimals (whitespace tolerated; empty, `+`, `-0`, leading zero, decimal point, exponent rejected); an `offset` at/beyond the row count is a 200 with empty `data`, echoed `limit`/`offset`, unwindowed `total_count`, `has_more` false — `validation.py:136-164`, `envelope.py:33-40`
- §2.3 (ordering) — insert — ambiguity — `created_at` ascending ties break on insertion order (`_seq`), and insertion order is the implicit final tie-break under every §4 alternative ordering — `store.py:135-137`
- §2.4 (timestamps) — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` come from the **real wall clock**, not the logical clock, and always render 3 fractional digits; all other `_utc` domain instants render `Z` with 3 fractional digits **only** when the sub-second part is non-zero (incl. `current_utc`) — `store.py:70-88`
- §2.4 (identity) — insert — ambiguity — serialization never omits a field; a valueless field is emitted as JSON `null` — `store.py:123-132`
- §2.5 step 5 — insert — ambiguity — a body FK that is absent, null, or not a JSON string is not looked up at all and falls through to step 6 — `validation.py:36-39, 203-208`
- §2.5 step 6 — insert — ambiguity — sub-check order (missing-required -> unknown-field -> per-field type/format in declared field order); explicit `null` == omitted (required -> missing breach, optional -> default); a JSON boolean never satisfies int/number; absent/unparseable body == `{}`, non-object body is itself the breach; timestamps accept `Z`/`z` and any offset and normalise to UTC with offset-less read as UTC; `email` = non-empty local + one `@` + non-empty domain, no whitespace, dot not required, 3-254 chars — `validation.py:26-33, 46-56, 84-129`
- §2.8 (logical clock) — insert — ambiguity — `to_iso8601` is mandatory and the only permitted body field; response is 200 with `data` holding only `current_utc`; the clock may move backwards — `routes_core.py:263-272`
- §3.1 (passengers) — insert — ambiguity — email uniqueness is a byte-exact comparison, so case-differing addresses are distinct — `routes_core.py:105-107`
- §4 preamble — insert — ambiguity — trailing slash tolerated (`strict_slashes = False`) — `app.py:27`
- §4 row `/policy-profiles/{id}/regulator-reports` — insert — ambiguity — ordered `period_start_utc` descending, ties most-recently-created first — `routes_core.py:87`
- §4 row `/bookings/{id}/consumer-complaints` — insert — ambiguity — `received_at_utc` ascending, ties ascending insertion order — `routes_core.py:235`
- §5 preamble — insert — ambiguity — three uncatalogued transport-layer identifiers: `ERR_NOT_FOUND` 404 (no route), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500; other framework 4xx reuse `ERR_INVALID_REQUEST` 400 — `app.py:46-58`

**Modules found fully pinned (no PRD edit needed)**
- `errors.py` — verified programmatically: all 59 `ERROR_HTTP` entries match the §5 table exactly, no impl-only or PRD-only codes, no status mismatches.

Every pinned behavior was verified against the live server (clock format, framework 404/405, trailing slash, non-object body, null-optional defaulting, out-of-range offset, `limit=010`, whitespace headers, FK-vs-shape precedence, boolean-for-int rejection, naive/offset timestamp normalisation) rather than reasoning from the code alone.

### Pass B summary (verbatim)

PASS B complete.

**PRD_COMPLETED.md line count: 419 before -> 419 after** (all edits are in-paragraph; Pass A's 15 edits untouched — verified by diff against PRD_FINALIZED.md).

**Counts: 14 ambiguity-pins, 3 mismatch-revisions** (17 pins across 15 Edit calls).

- §3.1 (leg creation) — insert — ambiguity — `scheduled_arrival_utc` <= `scheduled_departure_utc` now pinned as `ERR_INVALID_REQUEST` evaluated with the request-shape checks, hence ahead of `ERR_DUPLICATE_SEQUENCE_INDEX` — routes_segments.py:33-41
- §3.2 (cancellation) — insert — ambiguity — supplying `revised_arrival_utc` on a `CANCELLATION` pinned as `ERR_INVALID_REQUEST`, evaluated ahead of the leg's state check — routes_segments.py:132-138
- §3.2 (significant delay) — revise — mismatch — the delay-branch fare obligation is clamped to headroom and, on a zero clamp, is skipped with `suppressed_obligation_count` +1 and the request still succeeding — routes_segments.py:158-176, ledger.py:172-178
- §3.2 (re-declaration) — insert — ambiguity — skipping an already-existing fare obligation does **not** tick `suppressed_obligation_count`, and the booking's `version` still advances by 1 even when no derived booking field changes — routes_segments.py:159-176, ledger.py:56-60
- §3.2 (link two-a) — insert — ambiguity — each suspended sibling leg's own `version` advances by 1 — routes_segments.py:199
- §3.2 (link two-b) — insert — ambiguity — each cascade-voided ancillary purchase's own `version` advances by 1 — routes_segments.py:210
- §3.2 (link three-a) — insert — ambiguity — the proactive fare valuation reads leg statuses *after* link two-a, so just-suspended `DISRUPTED_UNUSED` siblings already count as unused value — routes_segments.py:190-214, calc.py:107-115
- §3.2 (`ARRIVED`) — insert — ambiguity — `occurred_at_utc` not strictly after `actual_departure_utc` answers `ERR_SEGMENT_STATE_INVALID` — routes_segments.py:277-278
- §3.2 (arrival bubble) — insert — ambiguity — each bubbled ancillary purchase's `version` advances by 1 — routes_segments.py:289
- §3.3 (mark-not-provided) — revise — mismatch — PRD said `refund_obligation_created` becomes true unconditionally; pinned the zero-clamp branch (no row, flag stays false, `suppressed_obligation_count` +1, request still succeeds, ledger recompute and booking `version` +1 either way) — routes_extras.py:100-115
- §3.3 (bag creation) — insert — ambiguity — `scheduled_delivery_utc` <= `checked_at_utc` pinned as `ERR_INVALID_REQUEST` ahead of the tag-uniqueness check — routes_extras.py:134-141
- §3.3 (bag resolve) — insert — ambiguity — the timestamp the *other* resolution would need is ignored when supplied and its field stays null — routes_extras.py:206-208
- §3.3 (delivered) — insert — ambiguity — an early delivery yields a negative `delivery_delay_hours`, stored as computed rather than clamped to 0 — calc.py:48-50, routes_extras.py:216-219
- §3.3 (on-time) — insert — ambiguity — the `DELIVERED_ON_TIME` branch runs no booking link: derived fields are not recomputed and the booking's `version` does not move — routes_extras.py:220-226
- §3.6 (obligation clock start) — revise — mismatch — an `ANCILLARY` obligation minted by the cancellation cascade takes the cancelled leg's `disruption_declared_at_utc` — routes_segments.py:217-228, routes_extras.py:47
- §3.6 (headroom step three) — insert — ambiguity — the `DENIED_BOARDING` exemption is tested *before* the issuance mode, so such an obligation is neither clamped nor refused in request-based mode either — ledger.py:168-182
- §2.3 (filters) — insert — ambiguity — filters match by exact string equality and an out-of-enum value is never a validation error (200, empty `data`, `total_count` 0) — routes_segments.py:84-88, routes_extras.py:60-64

**Modules with no edits of their own:** none was fully edit-free, but `calc.py`'s pure formula surface was already uniquely pinned and needed no change: the statutory ladder (rungs, 60/120/240-minute boundaries, round-before-cap, both caps), the 0.50 voluntary disclosure floor, `travel_credit_election_bonus_pct` rounding, the request-based per-leg proration, the proactive full-itinerary sum over unused statuses, `collected_total`/`consumed_cents`, `refund_deadlines`, the significant-delay per-leg at-or-above test, the booking-level bag threshold, the frozen tarmac deadline, and `settlement_method_for`. `ledger.py`'s `recompute_booking`, `recompute_credit_balance` and `append_activity` were likewise already exact.

One deliberate non-edit: `calc.whole_minutes` floors rather than truncates toward zero for negative intervals (§2.7 conflates the two), but every persisted minute field is either guarded by a strictly-after check or clamped at 0, so the divergence is unobservable through the API.

### Pass C summary (verbatim)

Pass C complete. All prior-pass edits verified intact.

- **PRD_COMPLETED.md line count:** 419 before -> **419 after** (every edit in-paragraph; table structure intact)
- **Char delta vs PRD_FINALIZED.md:** 108,568 -> **128,693 (+20,125)**; Passes A+B accounted for +8,127, so **Pass C added +11,998**
- **Edits:** 32 (**27 ambiguity-pins, 5 mismatch-revisions**)
- **Modules fully pinned with no edits: none.** All five of my modules produced edits.

**routes_denied.py**
- §3.4 P1 — insert — ambiguity — `voluntary_agreed_amount_cents` required/forbidden breaches are `ERR_INVALID_REQUEST` (400) and precede the two named gates — `routes_denied.py:37-46`
- §3.4 Plast — insert — ambiguity — minted obligation's `variant_applied` follows **effective** category, so recategorized rows get `INVOLUNTARY_STATUTORY` — `routes_denied.py:129-138`
- §3.4 Plast — revise — **mismatch** — suppression is keyed on resolved `compensation_cents == 0`, not "the free rung"; a voluntary free-rung record with agreed > 0 still mints — `routes_denied.py:140-160`, `ledger.py:168-171`
- §4 row `GET /denied-boarding-records` — revise — **mismatch** — filter accepted as `category` *or* `declared_category`, both matching declared `category`, `category` wins — `routes_denied.py:90-94`

**routes_tarmac.py**
- §3.5 P2 — insert — ambiguity — the new event is itself open-ended, so an existing occupation starting at/after the new start also collides => strictly increasing creation order — `routes_tarmac.py:44-50`
- §3.5 P3 — insert — ambiguity — no tarmac action ever recomputes the booking or moves its `version` — `routes_tarmac.py:98-102,135-140,176`
- §3.5 P5 — insert — ambiguity — `report_reference` 1-200 / `corrective_action_summary` 1-1000 chars; `filed_at_utc` carries **no** chronology rule — `routes_tarmac.py:144-148,175`

**routes_obligations.py**
- §3.6 P1 — insert — ambiguity — all four source FKs resolved for existence before basis matching, so an unknown `checked_bag_id` on a `FARE` create is `ERR_CHECKED_BAG_NOT_FOUND` — `routes_obligations.py:94-101`
- §3.6 P1 — insert — ambiguity — direct `GOODWILL_GRANT` create has no source ref and is never a duplicate — `routes_obligations.py:114-116`
- §3.6 P3 — insert — ambiguity — direct `GOODWILL_GRANT` gross is 0; `DENIED_BOARDING` variant keyed on the record's `effective_category`, incl. an unfinalized `RECORDED` record (gross 0) — `routes_obligations.py:76-84`
- §3.6 P5 — revise — **mismatch** — `request_received_utc` is optional on every basis/mode and is a *fallback only*, consulted when the basis-derived start is null — `routes_obligations.py:135-137`
- §3.7 P4 — insert — ambiguity — electing touches only the obligation; booking and passenger `version` do not move — `routes_obligations.py:240-241`
- §3.7 P5 — insert — ambiguity — consent existence + same-booking checks apply whenever `consent_complaint_id` is present, incl. a `CASH` election and a self-electing passenger — `routes_obligations.py:205,217-218,238-239`
- §3.7 P6 — insert — ambiguity — `processor_reference` (1-200) is validated but **not retained** — `routes_obligations.py:244,252`
- §3.7 P6 — insert — ambiguity — initiation does not recompute the booking — `routes_obligations.py:273-278`
- §3.7 P7 — insert — ambiguity — `FAILED` retains `settlement_attempt_count`/`settlement_initiated_at_utc`/election fields; no booking or passenger `version` bump — `routes_obligations.py:323-329`
- §3.7 P8 — insert — ambiguity — voiding from `INITIATED` is `ERR_OBLIGATION_STATE_INVALID`, **not** `ERR_OBLIGATION_NOT_VOIDABLE` — `routes_obligations.py:355-356`
- §3.7 P8 — insert — ambiguity — ancillary reset also discards the recorded instant and bumps the purchase's `version`; the bag rule bumps the bag's `version` and applies under **every** void reason — `routes_obligations.py:369-382`
- §2.1 Pownership — revise — **mismatch** — the refund-obligation **collection** narrows silently (PRD called the booking collection "the one exception"); filters/page applied after narrowing — `routes_obligations.py:173-181`
- §2.1 Pownership — insert — ambiguity — reading a single consumer complaint by id is deliberately **not** ownership-scoped — `routes_complaints.py:91-94`

**routes_complaints.py**
- §3.8 P3 — insert — ambiguity — request-info leaves `open_complaint_count` and the passenger row untouched; no complaint action touches the booking — `routes_complaints.py:142-161`
- §3.8 P4 — insert — ambiguity — `accessibility_resolution_code` / `granted_amount_cents` accepted and stored under dispositions that don't require them, minting nothing — `routes_complaints.py:186-221`
- §3.8 P4 — revise — **mismatch** — the three links are causal, not sequential: link two runs **before** any link-one write, so a duplicate/headroom refusal leaves the complaint, its trail and the passenger untouched; link three fires only when a row was minted — `routes_complaints.py:194-227`
- §3.8 P5 — insert — ambiguity — reopen retains `ack_breached`, `acknowledged_at_utc`, `answered_at_utc`, `granted_amount_cents`; later request-info measures against the *original* acknowledgement — `routes_complaints.py:151-152,252-259`
- §3.8 P6 — insert — ambiguity — full per-type `detail` mapping (category / `ACKNOWLEDGED` / note / disposition / reason / field name / `AUTO_CLOSED`) — `routes_complaints.py:86,131,159,223,261`
- §3.8 P6 — insert — ambiguity — activity rows carry **no** `version` and no `updated_at` — `ledger.py:238-251`
- §4 row `GET /consumer-complaints/{id}/activities` — revise — ambiguity — `activity_type` filter, applied after ordering and reflected in `total_count` — `routes_complaints.py:106-110`

**routes_reports.py**
- §3.9 phase two — insert — ambiguity — also writes `credit_bonus_cents` 0 and `payable_total_cents` = `amount_cents`; unlike phase one it does **not** exclude `SETTLED`/`VOIDED` rows — `routes_reports.py:258-271`
- §3.9 phase three — insert — ambiguity — each raised flag appends one `DEADLINE_BREACH_FLAGGED` row (up to two, ack before answer); already-true flags append nothing — `routes_reports.py:274-299`
- §3.9 Pidempotency — insert — ambiguity — version bumps are deferred past phase four, so a row mutated by several phases bumps **once**; idempotency also covers activity rows — `routes_reports.py:317-322`
- §3.9 Popen-report — insert — ambiguity — overlap check spans reports in every `status`, and only that profile's — `routes_reports.py:59-63`
- §3.9 Psubmit — insert — ambiguity — submit reads but never writes the profile; profile `version` does not advance — `routes_reports.py:177-182`
- §3.9 Pamend — insert — ambiguity — `amended_at_utc` is compared but not retained; `submitted_at_utc`/`submitted_by_user_id` keep the prior submission — `routes_reports.py:200-209`

§2.5's 17-step precedence ladder already pins essentially every error-precedence question in these five modules — all 20 endpoints were verified against it and every impl ordering matches, including the non-obvious pairs (`ERR_GRANT_AMOUNT_REQUIRED` before the complaint state check; `ERR_OPEN_COMPLAINT_IN_PERIOD` before `ERR_PERIOD_BOUNDS_INVALID` on submit; `ERR_SUBSTITUTE_BEFORE_SCHEDULED` before `ERR_SEGMENT_BOOKING_MISMATCH`). No precedence edits were made where §2.5 already decides the outcome.

**Prior-pass integrity confirmed:** all 18 original Pass A/B diff regions still differ from PRD_FINALIZED.md; spot-checked the §2.1 booking-collection narrowing sentence, the §2.1 whitespace-header clause (Pass A) and the §3.3 headroom zero-clamp sentence (Pass B) — all present.

### Step 9 aggregate + orchestrator verification

- Totals across the three passes: **64 edits — 55 ambiguity-pins, 9 mismatch-revisions.**
- `PRD_COMPLETED.md`: 419 lines / 128,693 chars vs source 419 lines / 108,568 chars (**+20,125 chars, +18.5%**; line count unchanged because every edit is in-paragraph).
- Orchestrator checks: `diff PRD_FINALIZED.md PRD_COMPLETED.md` yields 102 changed lines (51 pairs) — the file is emphatically NOT a byte-identical no-op; `grep "^#"` headers are byte-identical between the two, so no section was added or renamed; the file still ends on the complete final `| ERR_FAILURE_REASON_REQUIRED | 422 |` row of §5.
- Confirmed via `find -newermt` that no `.py` file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` was modified after the green sweep finished (01:03:30Z), so the 8/8 × 175/175 result remains the state of the delivered code. Steps 8 and 9 touched documentation only.

## Pipeline complete — 2026-09-04T01:52:00.000Z

All nine steps done. Final state: 175 tests, 8/8 parallel rounds green at 175/175, `PRD_COMPLETED.md` written.
