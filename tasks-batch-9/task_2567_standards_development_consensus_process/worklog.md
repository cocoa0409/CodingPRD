# Worklog — task_2567_standards_development_consensus_process

## Step 1: Create task directory — 2026-09-03T12:17:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2567_standards_development_consensus_process` and its `workspace/` subdirectory. Index 2567 was pre-assigned by the invocation (no scan of ./tasks/ performed, per orchestration instructions — concurrent pipelines on this host).

## Step 2: Generate Scaffold — 2026-09-03T14:18:00.000Z

Scaffold complete for scenario 2567 and lint-clean.

Final lint (run from `/home/ubuntu/github/CodingPRD`, verdict block verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2567_standards_development_consensus_process/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2567_standards_development_consensus_process/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2567_standards_development_consensus_process/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     84
  Calls scanned (§1.8+§1.9):  1789

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all absolute):
- `SCAFFOLD.yaml` — 3653 lines. Top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, priority_conflict_notes, endpoints, errors, roles. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2323 lines, single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 8082 lines, single top-level key `scaffold_corner_design`.

SCAFFOLD.yaml surface counts: 12 entities, 51 endpoints, 12 state-machine blocks, 12 calculations, 49 validation-ladder rules, 59 error codes, 6 roles, 2 concurrency rules, 2 priority-conflict notes. Profile: multi_party_negotiation + compliance_audit, layers optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers, cyclic state machines, segregation_of_duties, immediate consistency, difficulty_level expert_plus.

Design-index instance counts:
- §1.8 difficulty design: 18 instances across 9 groups.
- §1.9 corner design: 96 instances across all nine required sections — entities 13, state_machines 23, calculations 14, validations 24, endpoints 7, errors 4, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1. Of those, 84 carry a full `test_recipe` and 12 are `excluded_because` stubs deferring to a named §1.8 instance (the lint line "84 scanned" reflects the stub skip).

Cross-checks: all 114 instance names are unique across the two design files, and every one of the 59 declared error codes is referenced by at least one design instance (no untriggerable code).

## Step 3: Copy Shared Files — 2026-09-03T14:18:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T14:37:00.000Z

PRD generation for task_2567 is complete.

**Output:** `workspace/PRD.md`
**Size:** 486 lines, 108,791 bytes.

**Section outline**
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (fixed block, verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Clock · 2.5 Order of Precedence Among Validations · 2.6 Interest-Category Balance Arithmetic · 2.7 Version Pinning on Contended Writes · 2.8 Percentages, Rounding and Threshold Comparison · 2.9 The Consensus Gate and Cascade Discipline · 2.10 Two Conserved Quantities · 2.11 Two Interval Disciplines
- `## 3. Business Logic & Workflows` — 3.1 Participant registry / committee formation · 3.2 Proposing work and draft revisions · 3.3 Opening a ballot (effective kind, eligible set, window) · 3.4 Casting, changing, withdrawing a vote · 3.5 Closing a ballot, evaluating consensus, considering every negative · 3.6 Public review and the comment disposition record · 3.7 Patent disclosure, licensing commitments, call for patents · 3.8 Appeals and remedies · 3.9 Publication and the five-year maintenance cycle
- `## 4. API Endpoint Specifications` — 4-column table (Method, Path, Description, Authorized Role(s))
- `## 5. Error Code Catalogue` — 2-column table (Error ID, HTTP Status Code)

**Coverage**
- Entities: 12/12 · Field names: 135/135 verbatim in backticks (0 missing, includes `id`/`created_at`/`updated_at`/`version` and every endpoint input name)
- Endpoints: 51/51 rows (verified: 53 table lines = 51 + header + separator)
- State machines: 12/12 blocks over 10 entities; all 76 transitions documented, all 50 state names present, every `from`→`to` pair co-located in a single paragraph
- Calculations: 12/12, all constant values rendered as business numbers (3 seats, 3/2 categories, 50.0, 66.7, 50.1, 75.0, +5.0 capped at 90.0, streak 2, 0.1000, 100.0, 5 years, 180/90 days, 30 days, 14/30 days, 45 days, 15 days)
- Validation rules: 49/49 in the §2.5 precedence ladder carrying their scaffold priority numbers (10→119) plus both `priority_conflict_notes` worked cases
- Errors: 59/59 in §5; every non-404 error id also appears in narrative context in §2/§3
- Roles: 6/6 (`Proposer`, `CommitteeMember`, `CommitteeChair`, `PublicCommenter`, `StandardsStaff`, `AppealsBoard`)
- Enum members: 97/97 present; concurrency: both OCC rules documented in §2.7

**Hard Contracts**
- Contract 1 (Field-Name Coverage): **PASS** — two automated passes, 135 names, 0 missing.
- Contract 2 (Rule Coverage): **PASS** — full 49-rule ordered ladder, both OCC rules, all cascades and cross-entity side effects, dual-scope `applies_to` cases, all 76 transitions, all 12 calculations. Four gaps found and fixed during verification (explicit `RECEIVED`→resolved edges, `CAST`→`WITHDRAWN` edge, `ERR_BALLOT_NOT_OPEN`/`ERR_BALLOT_NOT_IN_VOTING_WINDOW` on vote revision, `ERR_CONSENSUS_GATE_BLOCKED` on periodic review).
- Contract 3 (§3 Path Purity): **PASS** — 1021 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path; also zero plain-text `/sdo` or `_clock` mentions in §3.
- Style: zero fuzzy words, zero pseudocode operators anywhere in the document.

**Not truncated:** the file ends at a real section boundary — the final row of the §5 error table (`| ERR_REAFFIRMATION_WINDOW_EXPIRED | 409 |`), a complete table row, with no audit footer and nothing mid-sentence.

Both design YAMLs were never opened, grepped or referenced, and no sibling task directory was accessed.

Scaffold inconsistencies resolved while writing (worth knowing for downstream steps): the disclosure endpoint description says `NOT_ESSENTIAL` while the entity enum says `NON_ESSENTIAL` — used the entity enum; `open_ballot_count` is defined over `OPEN` in the entity but `{OPEN, CLOSED}` in the capacity check — documented as both, reconciled since `CLOSED` is never externally observable; `approve-scope` advances `PROPOSED`→`SCOPE_APPROVED`→`IN_DEVELOPMENT` in one request (the second hop written as a system step); the ballot-window-length calculation comment claims it is checked before capacity, contradicting the priority ladder — the ladder governs.

**Orchestrator truncation check (independent):** `wc -l` = 486, `wc -c` = 108791, `grep '^## '` shows all five sections (lines 3, 11, 196, 364, 422), and `tail -12` ends on the complete final error-table row. PRD.md is NOT truncated; no regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T15:35:00.000Z

Done. Final state below.

## Module layout (3,525 lines total, 29 files)

`workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `app.py` | 93 | factory, 13 blueprints, §2.2 error envelope handlers, `PORT` default `10000`, binds `0.0.0.0` |
| `core/errors.py` | 115 | 59-code catalogue → HTTP status, `ApiError`/`fail()`/`bad_request()`, per-collection 404 map |
| `core/store.py` | 129 | 12 in-memory dicts, logical clock, `insert`/`touch`/`public`/`rows` |
| `core/validation.py` | 199 | `Body` allow-list (prec 40), `load_path` (30), `load_fk` (50), query filters |
| `core/util.py` | 138 | Decimal ROUND_HALF_UP helpers, inclusive comparators, date/instant math |
| `core/auth.py` | 87 | header auth (10), role gate (20), identity checks (60/62/64) |
| `core/envelope.py` / `core/enums.py` | 85 / 72 | envelope + pagination; enum tuples |
| `services/ballots.py` | 370 | tallies, thresholds, recirculation, close/evaluate |
| `services/graph.py` `balance.py` `reviews.py` `gate.py` `ip.py` `schedule.py` | 156 / 123 / 94 / 63 / 56 / 28 | traversal, interest-balance, comment ledger, publication gate, IP status, deadlines |
| `routes/` (13 modules) | 1,617 | work_items 282, appeals 225, votes 224, public_reviews 165, ballots 161, committees 138, comments 128, maintenance 126, patents 101, memberships 64, participants 43, clock 37, drafts 23 |
| `start.sh` (executable, 263 B) | — | installs only if flask missing, `exec python3 app.py` |
| `requirements.txt` | — | `flask==3.0.3` |

## Endpoint coverage: 51/51
`app.url_map` enumerates 52 rules; 51 are API endpoints and the 52nd is Flask's built-in `GET /static/<path:filename>`. The 51 match the PRD §4 table exactly (verified path-by-path). Error catalogue is 59/59 with zero symmetric difference against the PRD, and all 59 HTTP statuses match §5 (`mismatches: []`).

## Validation-precedence ladder
Precedence is encoded as *call order*, not as a rule table: every handler runs `auth.authenticate(roles)` (10/20) → `load_path` (30) → `Body(...)` construction and typed accessors (40) → `load_fk` (50) → identity/authority checks (60 chair, 62 vote owner, 64 actor-is-caller) → state checks (70–79) → OCC (80/81) → domain rules 90–119 in ascending numeric order. `Body` is a strict allow-list, so any unknown or non-writable field is a precedence-40 `ERR_INVALID_REQUEST` before any FK lookup — which is also what makes "supply a version field where none is declared" a malformed body rather than a stale-version error. Deliberate orderings verified: capacity (106) before window length (110); standing (97) before timeliness (117); duration (113) before buffer conflict (115).

## Optimistic concurrency
Exactly two endpoints pin a version, both required and both evaluated *after* every state check:
- `POST /sdo/public-reviews` — `expected_draft_version` vs `draft["version"]` → 412 `ERR_STALE_DRAFT_VERSION` (prec 80)
- `POST /sdo/patent-disclosures` — `expected_work_item_version` vs `work_item["version"]` → 412 `ERR_STALE_WORK_ITEM_VERSION` (prec 81)

Every mutated row goes through `store.touch()`, which bumps `version` by 1 and refreshes `updated_at` **at most once per request** (tracked in `flask.g._touched_rows`), and `insert()` pre-marks new rows so a row created in a request can never also take a bump in that same request. This keeps multi-hop cascades (appeal → ballot → draft → work item) at a single increment per affected row.

## Smoke boot
`PORT=57259 bash start.sh` — `ps` confirmed pid 3258608 was `python3 app.py` (exec replacement works, so per-test-server SIGTERM reaches Flask). Responses verified: 401 `ERR_UNAUTHENTICATED` envelope; empty list with `limit/offset/total_count/has_more`; participant create 201 with `version: 1`; `?limit=1` pagination; `POST /_clock/set_current_utc` returning `current_utc` + `promoted_public_review_ids`; unknown id → 404. All timestamps `2026-08-01T00:00:00.000Z` before the clock move and `2026-09-01T12:00:00.000Z` after; `api_request_id` matched `req_` + 20 uppercase alnum. Server killed with `kill 3258608` (explicit PID); pid gone and port 57259 free. No broad `pkill` was used at any point in this task. `__pycache__` cleaned; `py_compile` on all 29 `.py` files is clean.

Earlier full-flow runs (on ports 57231/57233/57237/57239, all killed by PID) also exercised: complete sub-ballot → public review → consensus ballot → publish → periodic review → reaffirm chain; the four-hop appeal UPHOLD/VACATE_BALLOT cascade with negative-count carryover; recirculation escalation to 75.0%; and 412 stale-version rejection.

## Constraint confirmation
No file under `test_helpers/` or `test_suite/` was read, listed, globbed, or grepped; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no sibling task directory was accessed. Sources were `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md`, and the generator SKILL.md. Storage is in-memory dicts only — no SQLite, no disk dump, no `/tmp` cache — and nothing is seeded, so a fresh process starts with twelve empty collections and the clock at exactly `2026-08-01T00:00:00Z`.

One fix applied this session beyond the route modules: `app.py`'s `PORT` default was `8080` and is now `10000`, matching the launcher contract in the skill.

**Orchestrator note on Step 5:** the first Step 5 subagent was killed mid-run by an infrastructure API error after it had completed the entire `test_helpers/` layer (2292 lines across 9 modules) plus `test_suite/conftest.py`, but before emitting any `test_*.py`. Its agentId was not returned with the error, so SendMessage resumption was impossible; a replacement subagent was spawned with an explicit resumption brief instructing it to read and build on the existing helper layer (extending/repairing in place, never rewriting) so the suite could not diverge from itself. Step 6 was launched in the same assistant message as that replacement, preserving the concurrency requirement.

## Step 5: Generate Unit Tests — 2026-09-03T16:30:00.000Z

The suite is complete and verified.

## Files written (`test_suite/`, 19 test modules + pre-existing `conftest.py`)

| File | Lines | Tests |
|---|---|---|
| test_01_ballot_consensus_arithmetic.py | 430 | 10 |
| test_02_committee_balance_and_holds.py | 257 | 6 |
| test_03_appeals_and_publication_gate.py | 292 | 6 |
| test_04_ballot_windows_and_capacity.py | 239 | 6 |
| test_05_review_windows_and_conserved_ledgers.py | 341 | 8 |
| test_06_representations_and_defaults.py | 372 | 7 |
| test_07_request_validation_and_existence.py | 254 | 8 |
| test_08_committee_activation_and_development_entry.py | 234 | 5 |
| test_09_initial_states_and_terminal_replays.py | 345 | 7 |
| test_10_close_cascade_breadth_and_routing.py | 401 | 5 |
| test_11_publication_periodic_review_and_reaffirmation.py | 385 | 5 |
| test_12_consensus_arithmetic_breadth_and_attendance.py | 375 | 5 |
| test_13_public_review_calendar_and_disposition.py | 419 | 6 |
| test_14_balance_labels_and_seat_admission.py | 288 | 5 |
| test_15_vote_admission_and_the_voting_window.py | 378 | 6 |
| test_16_authentication_roles_and_identity.py | 412 | 7 |
| test_17_segregation_of_duties_and_procedural_gates.py | 425 | 5 |
| test_18_appeal_window_and_patent_clearance.py | 435 | 6 |
| test_19_endpoint_surface_listings_and_immediate_consistency.py | 570 | 6 |
| **Total** | **6852** | **119** |

The last file written this session was test_19 (endpoints 0/1/2/3/6 + consistency_model 0), the final six untranslated instances.

## Counts and coverage audit (machine-checked, not eyeballed)
- **119 tests, 119 `Design:` tags** — one tag per test, exactly.
- **Queue A (Difficulty): 36 tags** over all **18/18** instances, every instance carrying exactly 2 tests; each tag's rule_id matches the yaml rule it lives under; no stub translated.
- **Queue B (Corner): 83 tags**, all distinct, each resolving to a real non-stub instance in the section its tag names: entities 13/13, state_machines 20/20, calculations 11/11, validations 20/20, errors 3/3, rbac 5/5, cross_cutting_complexity_layers 4/4, consistency_model 1/1, endpoints 6/7.
- Corner yaml holds 96 instances, 12 `excluded_because:` stubs, 84 non-stub → 83 translated, 1 skipped.
- Every one of the 28 `.py` files under `test_helpers/` and `test_suite/` passes `python3 -m py_compile` (0 failures), so no file is truncated. No occurrence of "scaffold", `xfail` or `pytest.mark.skip` anywhere in the generated code.

## Helper layer
`test_helpers/` (9 modules) and `test_suite/conftest.py` were **left completely unchanged** — no instance in either queue needed a new helper, and nothing needed repair.

## Skipped instance (PRD-first filter)
- **`Corner/endpoints/the_committee_read_reports_live_open_ballot_and_balance_counters`** — the design asserts `open_ballot_count == 1` while the ballot is OPEN and `== 0` after it becomes EVALUATED. `open_ballot_count` appears exactly once in PRD.md (line 240): a successful ballot *creation* refreshes it to the number of ballots in `status` `OPEN` or `CLOSED`. The PRD never states that a close, or a read, refreshes it, so the 1→0 transition with no intervening ballot creation is not uniquely derived. Skipped whole, per instruction — no weakened assertion, no xfail, no placeholder.

## Instances translated but corrected against the PRD (earlier sessions, reported for the record)
- `Corner/calculations[8]` — design withdrew from PUBLISHED; retranslated through the 180-day `OPEN_REVIEW` bound the PRD actually specifies.
- `Corner/errors[2]` — design's expected value contradicted PRD; asserted `periodic_review_due_date is None`.
- `Corner/validations[10]` — staff approval leaves `disposition_approved_by_participant_id` null (the id is recorded only for a chair approver), against the design's non-null expectation.

Two citation defects introduced in test_19 were caught and fixed before finishing: a paraphrased work-items listing row and a paraphrased `meta` sentence, both replaced with verbatim PRD spans; every quoted span in test_19 is now confirmed greppable in `workspace/PRD.md`. Also replaced an unsupported `source_type` listing filter with the PRD-declared `status` filter, and corrected a `unresolved_comment_count` assertion on a draft to `unresolved_negative_count` (that counter belongs to public reviews, not drafts).

The suite was never executed — Step 7 owns execution.

## Step 7: Run Tests and Iterate — 2026-09-03T17:05:00.000Z

All 8 result files are fresh, complete, no reaping. Clean sweep confirmed.

## Summary

**Iterations run:** 3 (each a full 8-round parallel sweep, 119 tests per round).

Every round of every sweep converged on the *same single* test — `test_03_appeals_and_publication_gate.py::TestUpheldAppealReopensDevelopment::test_upholding_carries_the_negative_forward_and_reopens_the_work_item` — which turned out to hide two independent defects, one per layer. No flakiness anywhere: all 8 rounds agreed exactly in all three sweeps, and no load-induced timeout/connection noise appeared.

**Tests deleted:** none. Every assertion in the failing test traces to a verbatim PRD sentence and is uniquely derivable, so deletion was not warranted.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_appeals_and_publication_gate.py`, `test_upholding_carries_the_negative_forward_and_reopens_the_work_item` — inserted the missing `decide_appeal("ACCEPT_FOR_REVIEW")` step before the `UPHOLD`. The test drove `UPHOLD` directly from `FILED`, a transition PRD §3.8 does *not* uniquely determine: PRD states an explicit source-state precondition for `ACCEPT_FOR_REVIEW` ("requires the appeal to be in `FILED`") and for `DENY` ("may be taken from `ACCEPTED_FOR_REVIEW` or directly from `FILED` — a procedurally deficient appeal may be denied **without a substantive review**"), but for `UPHOLD` states only the remedy rule plus terminality. That deliberate call-out for `DENY`, flagged as "the divergent branch", admits a faithful reader who requires `ACCEPTED_FOR_REVIEW` before an upholding — which is what this implementation does. Since the transition isn't uniquely derivable, the test may neither assert nor *depend on* it; routing the setup through the unambiguous path preserves all five assertions at full strength and matches the convention its own sibling test (line 34) and `test_11` (line 201) already use. No assertion was weakened and the implementation's check was left intact.

**Fixes applied to `implementation/`:**
- `routes/appeals.py`, `decide_appeal` — the `UPHOLD` cascade never re-derived patent clearance, so a work item returned to `IN_DEVELOPMENT` kept the stale `IP_CLEARED` it had earned at consensus approval. Added `ip.recompute(work_item)` immediately after hop four writes `IN_DEVELOPMENT`, gated on that transition actually having occurred. PRD §3.7 names this edge outright: "when an upheld appeal has returned a work item to `IN_DEVELOPMENT`, a recomputation on a work item that has no disclosures at all moves `IP_CLEARED` back to `IP_PENDING`, because reopening development reopens the call for patents." The existing `ip.evaluate` four-way rule already produced the right answer unaided — only the trigger was missing. Deliberately scoped to the reopen branch alone: the `SUSPEND_STANDARD` remedy is left untouched, since PRD states no clearance edge for `SUSPENDED` and adding one would be untraceable behavior. Version discipline is safe because `core.store.touch` is idempotent per request, so the extra recompute cannot double-bump the work item's `version`.

**Final sweep numbers (iteration 3):**

| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Passed/Total | 119/119 | 119/119 | 119/119 | 119/119 | 119/119 | 119/119 | 119/119 | 119/119 |

0 failures across all 8 rounds; all result files parse with the full 119-test list.

**Orchestrator independent verification of the sweep artifacts:** re-parsed all 8 `results.$i.json` directly — each reports `passed=119, total=119, failed=0`. Timestamp ordering confirms the green sweep postdates both fixes: `test_03_appeals_and_publication_gate.py` mtime 16:36, `routes/appeals.py` mtime 16:47, all 8 results files and `sweep.log` mtime 16:50, and `sweep.log` ends with eight `Results: 119/119 passed, 0 failed, 0 errors, 0 skipped` lines (durations ~214s each) plus clean port releases — no `Terminated`, so no reaping. Step 8 is therefore NOT skipped (1 `test_suite/` fix + 1 `implementation/` fix).

## Step 8: Finalize PRD — 2026-09-03T17:08:00.000Z

`PRD_FINALIZED.md` written with two surgical edits.

## Line counts
- `PRD.md`: 486 lines / 108,791 bytes
- `PRD_FINALIZED.md`: 486 lines / 109,138 bytes
- Delta: **0 lines (0.0%)**, +347 bytes (+0.32%) — both edits are intra-paragraph insertions.

## Changes
- **§3.7 (patent clearance derivation triggers)** — *insert* — added the upheld-appeal reopen to the normative list of moments the `ip_status` derivation runs: "…again inside the upholding of an appeal at the moment that upholding returns a work item from `CONSENSUS_APPROVED` to `IN_DEVELOPMENT`…". PRD already declared the *edge* (`IP_CLEARED` → `IP_PENDING` on reopen) but its trigger inventory omitted the trigger, which is exactly the defect Step 7 fixed — `implementation/routes/appeals.py:230` (`ip.recompute(work_item)`, gated on `reopened`).
- **§3.8 (UPHOLD)** — *insert* — pinned the source-state precondition PRD left open: UPHOLD requires the appeal to be in `ACCEPTED_FOR_REVIEW`; directly from `FILED` it is `ERR_INVALID_APPEAL_STATE` — `implementation/routes/appeals.py:152-155`.

## Per-edit pre-edit search log

**Edit A — §3.7 trigger list**
- (a) Subject: every code path that (re)derives a work item's `ip_status`, and every path that changes `progress_status` across the call-for-patents boundary without re-deriving.
- (b) Enumerated / read: `grep -rn "ip\.\(recompute\|evaluate\)"` → `services/ip.py:35,47` (`evaluate` four-way rule + `recompute`, incl. per-disclosure `blocks_publication` refresh and `touch` only-on-change); `services/ballots.py:246` inside `advance_to_consensus_approved`, called from `services/ballots.py:336` (close cascade hop four) and `:369` (adjudication clearing the last negative) — both already in the PRD list; `routes/patents.py:62` (disclosure recorded) and `:99` (commitment recorded) — already listed; `routes/work_items.py:194` (`ip.evaluate` as publication precondition — already listed) and `:212` (post-write `recompute` on publish, behaviorally a no-op since the call stays closed); `routes/appeals.py:230` (the new Step 7 trigger); `routes/work_items.py` `periodic_review` — confirmed by grep it calls **no** ip derivation, so `WITHDRAW`/`OPEN_REVIEW`/`REAFFIRM` leave `ip_status` untouched even though `WITHDRAWN` is not a call-closed state.
- (c) Adjustment: deliberately did **not** write a general rule such as "whenever `progress_status` changes" or "whenever an appeal is upheld" — either would falsely cover `SUSPEND_STANDARD` (`appeals.py:199-205`, no recompute), the non-reopen `REMAND`/`VACATE` case where the work item was not `CONSENSUS_APPROVED`, and periodic-review `WITHDRAW`. Wording narrowed to the exact `CONSENSUS_APPROVED` → `IN_DEVELOPMENT` transition, matching the `reopened` guard.

**Edit B — §3.8 UPHOLD source state**
- (a) Subject: appeal `status` transition preconditions across all three `decision` branches, plus every consumer of appeal status.
- (b) Enumerated / read: `routes/appeals.py:148-158` (all three source-state guards), `:160-169` (ACCEPT_FOR_REVIEW writes, ballot `APPEAL_PENDING` hold, gate recompute without version bump), `:171-180` (DENY from `FILED` **or** `ACCEPTED_FOR_REVIEW`, `_release_holds`), `:183-232` (UPHOLD cascade); `core/enums.py:62` `APPEAL_STATUS`; `services/gate.py:12` `LIVE_APPEAL_STATES = ("FILED", "ACCEPTED_FOR_REVIEW")`; confirmed by grep that `decide_appeal` is the only writer of `appeals[*]["status"]`.
- (c) Adjustment: phrased as a requirement on UPHOLD only, so PRD's existing sentences that DENY "may be taken from `ACCEPTED_FOR_REVIEW` or directly from `FILED`" and that "`UPHELD` and `DENIED` are terminal" stay verbatim and stay true (both terminal cases still fall out of the same three guards). Placed after the remedy-`NONE` sentence so the §2.5 ladder order (40 request shape before 75 appeal state, which is what the impl does — `Body`/remedy validation precedes the status guard) is not reordered.

## Step 9: Complete PRD — 2026-09-03T17:40:00.000Z

**Orchestrator decision (recorded per the autonomy directive):** Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one subagent, because a single agent scanning 29 modules against a 486-line / 109KB PRD reliably exhausts working context and produces a PRD_COMPLETED.md byte-identical to its input (i.e. the scan silently never ran). Partition: pass 1 = `app.py` + `core/*.py` + `services/*.py`; pass 2 = `routes/{work_items,appeals,votes,ballots,drafts,clock}.py`; pass 3 = `routes/{public_reviews,committees,comments,maintenance,patents,memberships,participants}.py`. Pass 1 owned the `cp` from PRD_FINALIZED.md; passes 2 and 3 edited in place. Each pass handed its deferred cross-module items forward explicitly, and pass 3 carried final whole-file integrity responsibility.

### Pass 1 (app.py + core/ + services/) — 17 changes: 12 ambiguity-pins, 5 mismatch-revisions
- §2.1 — insert — ambiguity — both auth headers are stripped before use; blank-after-strip is 401 — `core/auth.py:39-43`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` reads the **logical clock**, not wall time — `core/envelope.py:20,24`
- §2.3 — insert — ambiguity — empty `limit`/`offset` malformed, `limit` validated first; declared filters are exact case-sensitive equality, conjunctive; empty filter = absent; undeclared query params ignored — `core/validation.py:181-199`, `core/envelope.py:49-64`
- §2.3 — insert — ambiguity — `created_at` ties break by insertion order — `core/store.py:110`
- §2.4 — insert — ambiguity — a row advances `version` at most once per request; a row created in the request is never bumped again; a re-derivation writing no different value advances nothing — `core/store.py:83-97`
- §2.5 (prec. 40) — insert — ambiguity — length bounds measured on the untrimmed string and stored untrimmed; blank/non-string identifier body fields fail 400, not 404 at prec. 50 — `core/validation.py:65-82,139-150`
- §2.9 — insert — ambiguity — a work item with no `sponsoring_committee_id` does not fire the committee conjunct, so a fresh `PROPOSED` proposal is born `consensus_gate` `OPEN` — `services/gate.py:39-43`
- §2.9 — revise — mismatch — gate recomputation trigger list completed (scope decision, publication, periodic-review action) and negated (not on seat appointment, comment disposition, review close) — `routes/committees.py:136`
- §3.1 — insert — ambiguity — a no-op seat PATCH advances nothing and runs no cascade — `services/balance.py:110-116`, `routes/memberships.py:59-63`
- §3.1 (hop 3) — revise — **mismatch** — the gate is re-derived on **every** work item the committee sponsors whatever its `progress_status`; hops 1/3 on every seat change, hops 2/4 only on the drop from `ACTIVE` — `services/gate.py:60-63`, `services/balance.py:110-123`
- §3.3 — insert — ambiguity — effective-kind fallback chain when the predecessor draft holds no `EVALUATED`/`VACATED` ballot — `services/ballots.py:86-99`
- §3.3 — insert — ambiguity — recirculation set rules: group one enters on the cast vote alone; `appointed_at` strict; no predecessor → full active roster; seat identities frozen — `services/ballots.py:102-124`
- §3.3 — revise — ambiguity — window span is the exact elapsed interval with fraction retained, validated after the effective kind; `opens_at >= closes_at` also reports `ERR_BALLOT_WINDOW_TOO_SHORT` — `core/util.py:131-133`
- §3.3 — insert — ambiguity — a ballot close refreshes `open_ballot_count` but does not advance the committee's `version` — `services/ballots.py:328-330`
- §3.5 — revise — **mismatch** — attendance sweep advances every missed seat's `version`, not just suspended ones; already-`SUSPENDED`/`WITHDRAWN` seats still take the streak increment — `services/ballots.py:273-293`
- §3.5 — insert — ambiguity — the sweep runs between hop 3 and hop 4, so a committee suspended by this very close blocks the `CONSENSUS_APPROVED` advancement in the same request — `services/ballots.py:326-336`
- §3.5 — revise — **mismatch** — the final reading re-runs the whole verdict; `COMMENT_RESOLUTION` exits read the refreshed `consensus_result`; linked comment advances only on `PERSUASIVE`/`NON_PERSUASIVE`; draft and work item advance on every adjudication — `services/ballots.py:341-370`
- §3.7 — insert — ambiguity — every `ip_status` re-derivation refreshes `blocks_publication` on all disclosures without advancing their `version` — `services/ip.py:47-52`
- §3.9 — insert — ambiguity — "latest draft" ties on `revision_number` break to most recently created — `services/graph.py:130-138`
- §4 — insert — **mismatch** — unrouted path → `ERR_INVALID_REQUEST` at 404, unsupported method → 405; unparseable/non-object JSON → 400; absent body reads as `{}` — `app.py:61-78`

### Pass 2 (routes/work_items, appeals, votes, ballots, drafts, clock) — 23 changes: 15 ambiguity-pins, 8 mismatch-revisions
- §3.3 — revise — mismatch — the draft's own `status`, not the submitted `ballot_kind`, decides admissibility and the transition; `APPROVED` admitted only for `REAFFIRMATION`; kind/status pairing otherwise unpoliced convention — `routes/ballots.py:55-80`
- §3.3 — insert — ambiguity — the committee `ACTIVE` check runs after the two draft-status checks — `routes/ballots.py:82-88`
- §3.3 — insert — ambiguity — `ERR_PUBLIC_REVIEW_NOT_APPROVED` keys off the draft being `PUBLIC_REVIEW_CLOSED`, not the requested/effective kind — `routes/ballots.py:90-95`
- §3.3 — insert — ambiguity — a new ballot's `pending_negative_count` starts at 0 — `routes/ballots.py:130-155`
- §3.3 — insert — ambiguity — `opens_at`/`closes_at` echoed exactly as supplied, not renormalised; window arithmetic uses parsed instants — `routes/ballots.py:145-146`
- §3.2 — revise — mismatch — draft revision admits any caller holding `CommitteeChair`; no check against `chair_participant_id` — `routes/work_items.py:104`
- §3.2 — insert — ambiguity — `ballot_round_count` counts every ballot row ever created against the revision (`VACATED` included), refreshed only on ballot open — `routes/work_items.py:130`
- §3.2 — insert — ambiguity — creating a draft versions the parent work item but does not re-derive its gate/`unresolved_negative_count`; a predecessor need not belong to the same work item — `routes/work_items.py:104-140`
- §3.2 — insert — ambiguity — a decision is admitted only while `PROPOSED`, ahead of the committee-status check; `designation` 1–32 non-blank — `routes/work_items.py:150-190`
- §3.2 — revise — mismatch — the carryover ledger is written when an upheld appeal reaches a draft either by vacating or by remanding — `routes/appeals.py:207-219`
- §3.5 — revise — mismatch — closing a ballot admits any `CommitteeChair`, no chair-identity check — `routes/ballots.py` `close_ballot`
- §3.4 — insert — ambiguity — full field shape of the server-filed objection comment — `routes/votes.py:18-34`
- §3.4 — insert — ambiguity — casting resets the seat's `missed_ballot_streak` and advances the seat's `version` unconditionally — `routes/votes.py:92-93`
- §3.4 — insert — ambiguity — PATCH accepts only `position`/`status`/`comment_text`; change to `NEGATIVE` with no objection files one; `comment_text`-only revision does not touch `position_change_count`; no-op PATCH advances nothing — `routes/votes.py:112-164`
- §3.4 — insert — ambiguity — revising an already-`WITHDRAWN` vote is `ERR_INVALID_REQUEST` (400), after the ballot-open and voting-window checks — `routes/votes.py:140-141`
- §3.8 — revise — mismatch — a `VACATED` ballot keeps its `closed_at`, so it still anchors the 30-day window — `routes/appeals.py:37-41,190-197`
- §3.8 — revise — mismatch — `ACCEPT_FOR_REVIEW` re-derives the gate **without** a forced bump — `routes/appeals.py:167-169`
- §3.8 — insert — ambiguity — acceptance records the rationale, leaves `decided_at` null, ignores any submitted `remedy` — `routes/appeals.py:160-169`
- §3.8 — revise — mismatch — a denial versions the appeal, the work item (forced bump), and every ballot whose `APPEAL_PENDING` hold it released — `routes/appeals.py:171-180`
- §3.8 — revise — mismatch — UPHOLD cascade rewritten (vacate releases hold to `NONE`; no vacatable ballot → no downstream hops; target draft resolution; `REMAND_TO_COMMITTEE` does not release the hold; `SUSPEND_STANDARD` on a non-`PUBLISHED` item still versions it) — `routes/appeals.py:182-232`
- §3.9 — insert — ambiguity — publication derives the gate afresh in-request; the draft read is the most recently created `APPROVED` draft; no `APPROVED` draft draws the same `ERR_PUBLIC_REVIEW_NOT_APPROVED` — `routes/work_items.py:190-215`
- §3.9 — revise — ambiguity — periodic review's `rationale` shape-checked then discarded; gate derived afresh and checked after the per-action status check; all three branches write `last_periodic_action_at` — `routes/work_items.py:217-282`
- §2.4 — insert — ambiguity — the clock response's `data` is exactly `current_utc` plus `promoted_public_review_ids` in ascending creation order — `routes/clock.py:18-37`

Pass 2 also corrected a misreading in pass 1's handoff: `appeals.py:179` is the `DENY` branch, not `ACCEPT_FOR_REVIEW`; acceptance calls `gate.recompute` with no bump, so the true behavior was pinned instead of a spurious version advance.

### Pass 3 (routes/public_reviews, committees, comments, maintenance, patents, memberships, participants) — 23 changes: 15 ambiguity-pins, 8 mismatch-revisions
- §3.1 — insert — ambiguity — brand-new committee's balance fields on the empty roster — `routes/committees.py:28-45`
- §3.1 — insert — ambiguity — appointment has no committee-`status` precondition; a null `employer_affiliation_code` is never caught by the affiliation rule — `routes/committees.py:101-123`
- §3.1 — insert — ambiguity — the four seat edges are exhaustive; any other move is `ERR_INVALID_REQUEST` (400) with nothing applied, not even an accompanying `voting_rights` flip, which stays available on a `WITHDRAWN` seat — `routes/memberships.py:16-21,46-47`
- §3.1 — insert — ambiguity — neither `status` nor `voting_rights` is required; a body naming neither is a lawful no-op — `routes/memberships.py:41-42,59`
- §3.1 — insert — ambiguity — cascade hop four's stamp overwrites an existing `APPEAL_PENDING` hold, which then outlives the appeal's denial and is cleared only by re-activation — `services/balance.py:119-122`
- §3.1 — revise — mismatch — hops one and three run on every *edit of an existing seat*; a new appointment runs hop one alone — `routes/committees.py:136-137` vs `routes/memberships.py:63`
- §3.5 — insert — ambiguity — adjudicability never consults the ballot's `status`, so a pending negative on a `VACATED` ballot stays adjudicable and its tallies are rewritten — `routes/votes.py:189-191`
- §3.5 — insert — mismatch — the three edges out of `COMMENT_RESOLUTION` are exhaustive and none fires where no ballot is `EVALUATED` — `services/ballots.py:350-364`
- §3.5 — revise — mismatch — "leaves `COMMENT_RESOLUTION`" → "**ordinarily** leaves" (false universal) — `services/ballots.py:350-364`
- §3.6 — insert — ambiguity — `start_date > end_date` draws `ERR_REVIEW_PERIOD_TOO_SHORT` (409), not 400 — `routes/public_reviews.py:49-52`
- §3.6 — insert — ambiguity — the cross identifier is optional-then-ignored: resolved (draft before review before submitter) then discarded — `routes/comments.py:35-59`
- §3.6 — insert — ambiguity — close calls `recompute_counters`, not `refresh`, so a fully-dispositioned review closes to `CLOSED` at 100.0 and waits for a later disposition action — `routes/public_reviews.py:117`
- §3.6 — insert — ambiguity — any comment may be dispositioned whatever its `source_type`; `COMMITTEE`/`BALLOT_NEGATIVE` rows touch no ledger — `routes/comments.py:88-128`
- §3.6 — insert — ambiguity — a `disposition_rationale` sent with `REOPENED` is shape-checked then discarded — `routes/comments.py:94-96,114-115`
- §3.7 — insert — ambiguity — disclosure examines no `progress_status`; `patent_number` has no uniqueness constraint — `routes/patents.py:28-59`
- §3.7 — insert — ambiguity — `commitment_letter_ref` 1–80; no identity check beyond role admission; freely re-recordable, last write wins; letter/`committed_at` written only on the two RAND branches — `routes/patents.py:80-101`
- §3.7 — insert — mismatch — disclosure and commitment advance the work item's `version` unconditionally — `routes/patents.py:62-63,97-100`
- §3.9 — insert — ambiguity — `clause_reference` 1–40; submission has no `progress_status` precondition at all — `routes/maintenance.py:36-65`
- §3.9 — revise — mismatch — the chair-identity test keys off the caller's role: a `CommitteeChair` must match `chair_participant_id` on all three actions while `StandardsStaff` is never subject to it; `response_text` 1–2000 required on all three — `routes/maintenance.py:85-95`
- §3.9 — insert — ambiguity — the two issuing branches advance the parent work item's `version`; `DECLINE` does not — `routes/maintenance.py:119-125`
- §3.9 — revise — mismatch — `ISSUE_INTERPRETATION` is conventionally the chair's branch but unpoliced (either admitted role may take either issuing action) — `routes/maintenance.py:83,104-112`
- §3.9 — revise — mismatch — `ISSUE_ERRATUM` same convention-not-restriction wording — `routes/maintenance.py:83`
- §3.9 — revise — mismatch — "Note the asymmetry" reworded: an interpretation is available in any state short of `WITHDRAWN`, including a work item with no sponsoring committee, which only the secretariat can resolve — `routes/maintenance.py:94-99`

### Cross-pass handoff resolution
1. Seat-edge violation error → RESOLVED (`ERR_INVALID_REQUEST` 400, nothing applied).
2. Draft-status ↔ `ballot_kind` "fixed" claim → RESOLVED as a live mismatch; §3.3 revised.
3. `ballot_round_count` including `VACATED` → RESOLVED.
4. Adjudication on a vacated ballot → RESOLVED; three edits pin both the rewrite of a `VACATED` ballot's figures and the draft that can be stranded in `COMMENT_RESOLUTION`.
5. Adjudication and the review ledger (`routes/votes.py:217-221`) → CONFIRMED UNREACHABLE dead code, no PRD change.
6. Overwritten `APPEAL_PENDING` hold → RESOLVED (§3.1 hop four).
7. Non-approved later review during `CONSENSUS_BALLOT` (`services/ballots.py:264-268`) → CONFIRMED UNREACHABLE, left unpinned rather than documenting dead code.

### Totals and integrity
- `PRD_FINALIZED.md` 486 lines / 109,138 chars → `PRD_COMPLETED.md` 486 lines / 132,983 chars. **+23,845 chars (+21.8%), 0 lines** — every one of the 63 edits is an in-paragraph insert or revision; no new sections, no new paragraphs.
- Three-pass totals: **63 changes — 42 ambiguity-pins, 21 mismatch-revisions.**
- Pass-3 whole-file integrity check: five `## ` sections at L3/L11/L196/L364/L422 in order; §4 endpoint table 51 rows; §5 error table 59 rows; ends at `| ERR_REAFFIRMATION_WINDOW_EXPIRED | 409 |`; pass-1 and pass-2 edits spot-checked intact; `cmp` vs PRD_FINALIZED.md → differs (not byte-identical, so the scan demonstrably ran).
- **Orchestrator independent verification:** `wc -l` 486 / `wc -c` 132,983; `grep -c '^## '` = 5; `cmp -s` vs PRD_FINALIZED.md reports a difference; `tail -2` ends on the complete final error-table row. Step 9 output confirmed present and untruncated.
- Step 9 edits documentation only — `implementation/` and `test_suite/` were untouched after Step 7, so the verified 8×119/119 sweep remains the pipeline's final test state.

**PIPELINE COMPLETE.**
