# Worklog — task_2479_youth_tournament_housing_stay_to_play_administration

## Step 1: Create task directory — 2026-09-02T23:08:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2479_youth_tournament_housing_stay_to_play_administration` and its `workspace/` subdirectory. Index 2479 fixed by scenario number per orchestration instructions; no scan of ./tasks/ performed and no other task directory created.

## Step 2: Generate scaffold — 2026-09-03T00:48:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Output directory:** `/home/ubuntu/github/CodingPRD/tasks/task_2479_youth_tournament_housing_stay_to_play_administration/`
- `SCAFFOLD.yaml` (2948 lines) — §1.0–§1.7, 13 top-level keys, neither design key present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1686 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (4344 lines) — single key `scaffold_corner_design`

**Lint verdict (verbatim, first run of the final file):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2479_youth_tournament_housing_stay_to_play_administration/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2479_youth_tournament_housing_stay_to_play_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2479_youth_tournament_housing_stay_to_play_administration/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     82
  Calls scanned (§1.8+§1.9):  1301

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Scaffold contents**
- Profile: `quota_allocation` primary / `ledger_reconciliation` secondary; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`; topology `graph`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`.
- **13 entities:** Tournament, Hotel, HotelContract, RoomBlock, Team, TeamRegistration, Booking, RoomingListEntry (immutable), ExceptionRequest, Complaint, RebateInvoice, RevenueDistribution, ActualizationReport (immutable).
- **9 state-machine blocks** (Booking carries two parallel axes: `booking_status` and `rebate_status`), **2 concurrency rules**, **16 calculations** (interval_merge, tiered_pricing, waterfall_allocation, weighted_scoring, constraint_propagation invariants, plus 2 dual-variant rules), **55 validations**, **44 endpoints**, **64 error ids**, **5 roles**.

**Design instances**
- §1.8: 18 difficulty instances (260 calls).
- §1.9: **104 instances** across all nine claim-extraction sections — entities 13, state_machines 15, calculations 15, validations 9, endpoints 6, errors 31, rbac 8, cross_cutting_complexity_layers 6, consistency_model 1. Of those, 82 carry full `test_recipe`s and 22 are `excluded_because` stubs citing named §1.8 instances (all citations resolve; no stub carries a recipe).
- Verified: no duplicate instance names within §1.9 or against §1.8; no forbidden concurrency vocabulary; every one of the 64 error ids is reachable (the `errors` section opens with a comment-block coverage map showing where each is asserted); both `concurrency_rules` entries have stale-version tests on their declared `write_endpoint`/`occ_field`.

Two scaffold-level ambiguities were resolved during the corner walk and are pinned explicitly in the affected instances' `distinguishing_aspect` so the PRD writer inherits the decision: the rooming-list rules are layered so priority 60 owns index shape (starts at 1, no gaps/duplicates) and priority 62 owns cardinality vs `rooms_requested` — otherwise 62 would be unreachable; and `ERR_ROOMING_LIST_OCCUPANT_MISMATCH`, which §1.8 deliberately masks behind `ERR_CHAPERONE_REQUIRED`, gets its own unmasked trigger.

## Step 3: Copy shared files — 2026-09-03T00:49:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2479_youth_tournament_housing_stay_to_play_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T01:07:00.000Z

All three hard contracts verified. Final report:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2479_youth_tournament_housing_stay_to_play_administration/workspace/PRD.md` — **507 lines**

**Sections written**

- `## 1. Introduction` — 3 paragraphs (hotel-economics tension, scope of both market sides, two design commitments)
- `## 2. Global Specifications & System-Wide Principles` — 12 domain-derived subsections: 2.1 Actors/Headers/RBAC, 2.2 API Response Structure (byte-verbatim), 2.3 Pagination and List Ordering, 2.4 Resource Identity/Timestamps/Record Versions, 2.5 The Logical Housing Clock, 2.6 Path Resolution and Reference Integrity, 2.7 Rooms/Cents/Rounding Discipline, 2.8 Stale-Version Guards, 2.9 Posture Propagation and Cascade Discipline, 2.10 Segregation of Duties, 2.11 Rejection Precedence (55-item ordered ladder), 2.12 Conservation Invariants
- `## 3. Business Logic & Workflows` — 9 subsections following the business timeline: 3.1 Standing Up an Event, 3.2 Hotel Contracting and Room Block Inventory, 3.3 Registration and Roster-Based Requirements, 3.4 Booking/Rooming Lists/Confirmation, 3.5 Superseding, Cancelling and the Deadline-Tier Penalty, 3.6 Exceptions/Information Loops/Appeals, 3.7 Closing the Window, Actualization and Rebate Accrual, 3.8 Rebate Invoicing, Attrition and Collection, 3.9 Complaints, Remedies and Revenue Distribution
- `## 4. Endpoint Definitions` — status-code paragraph + 4-column table, 44 rows
- `## 5. Error Code Catalogue` — 2-column table, 64 rows

**Tail confirmation:** the file ends with the final `ERR_COMPLAINT_SUBJECT_MISSING | 422` row of §5 — a complete final section, no sentinel markers left, no audit footer, nothing mid-sentence. §2.2 diffs clean against `section-2.2-response-structure.md`. No difficulty meta-language present; neither withheld design file was opened.

```
Field coverage check:
- entities[].fields: 139 required, 139 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 44 required, 44 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 55 checked, 55 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing
- validations[] conditions: 55 checked, 55 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 23 side-effect endpoints + 55 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 139 checked, 139 reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1007
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two scaffold inconsistencies resolved in the PRD's favour of the state machine / field definitions, worth flagging: (1) the invoice `lifecycle` endpoint description says `WRITE_OFF` moves `DISPUTED → WRITTEN_OFF` while the state machine declares three source states (`ISSUED`, `PARTIALLY_PAID`, `DISPUTED`) — the PRD documents all three; (2) `RebateInvoice.distributed_cents` is defined on the entity as the sum of distribution `gross_collected_cents` but the endpoint side effect says it adds `distributable_cents` — the PRD states the entity-level definition and notes it updates at distribution creation.

**Orchestrator verification (truncation guard):** independently confirmed 507 lines, five top-level sections (`## 1`–`## 5`), and that the tail is a complete §5 error-table row (`ERR_COMPLAINT_SUBJECT_MISSING | 422`) — not mid-sentence. Grep for `expert level` / `harder than` / `scaffold` in PRD.md returns no matches, so no difficulty meta-instruction leaked. No regeneration needed.

**Orchestrator note on Steps 5 and 6:** both were launched concurrently in a single assistant message, so the implementation generator started before `test_suite/` existed on disk — physical isolation preserved.

## Step 5: Generate unit tests — 2026-09-03T02:52:00.000Z

Test generation is complete and audited.

## Files written

**Stage 1 — `<task root>/test_helpers/`** (9 modules, unchanged since the queue-A work): `types.py`, `api_errors.py` (64 error ids matching PRD §5 one-for-one, zero status mismatches), `constants.py`, `test_users.py`, `api_client.py`, `factories.py`, `assertions.py`, `fixtures.py` (layered `Env` pipeline builders), `__init__.py` (172 exports).

**Stage 2 — `<task root>/test_suite/`**: `conftest.py` + 19 test files, **144 tests total**.

| queue | files | tests |
|---|---|---|
| A (Difficulty) | `test_01`…`test_09` | 36 |
| B (Corner) | `test_10_entities` 17, `test_11_consistency_model` 2, `test_12_state_machines` 11, `test_13_calculations` 14, `test_14_errors_part_a` 13, `test_15_errors_part_b` 11, `test_16_validations` 10, `test_17_endpoints` 8, `test_18_rbac` 16, `test_19_cross_cutting_complexity_layers` 6 | 108 |

## Coverage

- **Queue A: 18/18** difficulty instances, exactly 2 tests each.
- **Queue B: 80/82** non-stub corner instances (≥1 test each); the 22 `excluded_because` stubs correctly received none.

## Audit results (all clean)

- `pytest --collect-only` → 144 collected, no import or collection errors.
- Design-tag check: every test docstring ends with exactly one `Design:` line; all 98 distinct tags resolve to real non-stub instances in the source yamls; no untagged, dual-tagged, or stub-tagged tests.
- Citation check: every `PRD §x: "…"` quote is present verbatim (whitespace-normalised) in `workspace/PRD.md`; every test carries at least one citation.
- `pyflakes` silent across `test_suite/` and `test_helpers/`; no private-name imports; no `skip`/`xfail`/`skipif` anywhere; no occurrence of "scaffold"/"design index" in generated code.
- `test_helpers/` and `conftest.py` were not modified during queue B (verified by mtime); nothing under `workspace/implementation/` was read or written.

## Instances skipped (2, both PRD-first filter failures)

1. `Corner/errors/rooming_list_entry_count_mismatch_rejected` — `ERR_ROOMING_LIST_ROOM_COUNT_MISMATCH` is unreachable as the PRD is written. §3.4 checks the index rule ("the contiguous sequence from 1 through the booking's `rooms_requested`") *before* the count rule, and any entry set whose cardinality differs from `rooms_requested` necessarily violates the index sequence first, so §2.11 item 34 always wins over item 35.
2. `Corner/cross_cutting_complexity_layers/close_booking_cascade_is_all_or_nothing` — §3.7 states the "at least one `EXECUTED` or `CLOSED` contract" precondition for close-booking but names no error id, and §2.11 item 13 does not apply (the tournament *is* in a declared source state). No error is uniquely derivable.

## Notable PRD-vs-design divergences (PRD followed in every case)

- Several recipes send `"outcome": "UPHELD"`/`"DISMISSED"` to `/complaints/{id}/adjudicate`; PRD §3.9 declares the request vocabulary as `UPHOLD`/`DISMISS` with UPHELD/DISMISSED as resulting statuses. Tests send the PRD's values.
- One recipe uses complaint category `"PRICING"` (not in §3.9's vocabulary) — translated to `PRICING_FAIRNESS`.
- One recipe expects `distributed_cents` = the distributable amount; §3.8 defines it as the sum of `gross_collected_cents`, so the derived value is asserted instead.
- Two rbac recipes probed scope enforcement through GET routes; §2.1 scope-guards only the enumerated POSTs, so PRD-declared POST probes were used.
- One recipe's `APPEAL` payload carried `justification`, which §3.6 reserves for `RESUBMIT` (and §2.6 refuses unknown fields) — dropped.

## PRD friction worth flagging to the spec author

- `ERR_ROOMING_LIST_ROOM_COUNT_MISMATCH` (§2.11 item 35, §5) appears dead under §3.4's literal index rule — the only genuine internal contradiction found.
- Two preconditions are stated without any error id and have no §5 catch-all: close-booking's "at least one `EXECUTED` or `CLOSED` contract" (§3.7) and contract `SUBMIT`'s "at least one room block" (§3.2).
- §2.3's default `created_at`-ascending ordering leaves same-instant multi-row lists (rooming-list entries, blocks created in one setup) order-indeterminate.

## Step 6: Generate implementation — 2026-09-03T02:19:00.000Z

## Done — implementation complete and verified

### Files written (all in `/home/ubuntu/github/CodingPRD/tasks/task_2479_youth_tournament_housing_stay_to_play_administration/workspace/implementation/`)

| File | Role |
|---|---|
| `store.py` | In-memory dict store (13 collections), logical UTC clock starting `2026-08-01T00:00:00Z`, id/date helpers |
| `errors.py` | 64-entry error catalogue + `ApiError` |
| `core.py` | Envelope (`meta`/`response_type`/`data`), auth ladder steps 1–4, schema validation, pagination/filters |
| `calc.py` | All calculation rules and constants (rounding modes per PRD: HALF_UP money, CEILING room nights, FLOOR party shares) |
| `domain.py` | Recompute/cascade layer — registration compliance, block occupancy/posture, contract posture, tournament pressure, the four named chains, conservation-preserving freezes |
| `views.py` | All 44 routes, each with ladder-ordered checks (step numbers commented inline) |
| `app.py` | Flask app, `ApiError` handler, 404/405/500 envelopes, `app.run(host="0.0.0.0", port=$PORT)` |
| `requirements.txt` | `flask>=3.0` |
| `start.sh` | Launcher (executable) |

### Endpoint count: 44 — exact parity with the scaffold
Programmatic diff of the Flask URL map against `SCAFFOLD.yaml` `endpoints:` gives `spec 44 / impl 44`, **zero missing, zero extra**, and every declared success code matches (12 creates at 201 — including `POST .../actualizations`; `POST .../rooming-list` at 200; all others 200).

### Error catalogue: 64 codes, statuses byte-matched
Diffed against the PRD §5 status table: 64/64 present, **zero status mismatches**, zero extras. (The "66" figure in my earlier notes was wrong — the real catalogue is 64; the scaffold's 65th match was the `ERR_XXX` placeholder in its envelope example.)

### `start.sh` confirmation
- Honours `$PORT` (`PORT="${PORT:-10000}"`, exported and read by `app.py`)
- Binds `0.0.0.0` — server log confirms `Running on all addresses (0.0.0.0)`
- Runs in the **foreground** via `exec python3 app.py`, no fork, no reloader (`use_reloader=False`)
- pip install guarded by `if ! python3 -c "import flask"`, so relaunch-per-test costs nothing

### Storage
In-memory dicts only. Grep confirms no `sqlite`, no file `open(`, no `json.dump`, no `pickle`, no `/tmp`; the only `os.environ` use is `PORT`. Fresh boot returns `total_count: 0` on every list endpoint and `api_request_timestamp: 2026-08-01T00:00:00.000Z` — nothing is seeded, preloaded or hardcoded.

### Verification
Three end-to-end scenarios, **171 assertions, all passing on a fresh boot** (re-ran the whole set against a newly launched process to mimic `--isolation per-test-server`):
1. Full happy path: tournament → hotel → team → contract → block → SUBMIT/COUNTERSIGN → registration → booking → rooming-list → confirm → close-booking (with release sweep) → actualization → invoice with attrition penalty exceeding rebate (total_due clamped to 0).
2. Money path end-to-end: exception review loop (START_REVIEW/REQUEST_INFO/RESUBMIT/APPROVE), complaint triage + FEE_WAIVER remedy crediting a cancellation penalty, invoice ISSUE → partial remit → distribution (admin fee 8%, floor shares 460/276/184, remainder to organizer) → APPROVE → PAY → full remit → bookings COLLECTED → tournament `SETTLED`; plus auth ladder, pagination and filter-validation errors.
3. Corner behaviour: REVISE round-trip, hotel night capacity, release-deadline-before-cutoff, block posture flip to `RESTRICTED` at exactly 0.90 → contract `SOLD_OUT` → tournament `CONSTRAINED` → LOCAL_TEAM auto-approval, `ERR_BLOCK_RESTRICTED_TO_UNHOUSED_TEAMS`, closed-interval team-stay overlap, supersede (target auto-cancelled with 25%-tier penalty), appeal + `ERR_SOD_SAME_REVIEWER` + appeal limit, ESCALATE resetting `appeal_count` + `ERR_SOD_ADJUDICATOR_CONFLICT` + POLICY_EXEMPTION cascade re-approving a denied request, block release, and the **two attrition variants diverging** (per-block shortfall 5 billed vs contract-aggregate 0 reported-only) → DISPUTE → partial remit rejected → WRITE_OFF.

Two spec-conflict resolutions worth flagging, both decided in favour of PRD narrative over scaffold endpoint prose: `distributed_cents` is the sum of `gross_collected_cents` over the invoice's distributions (verified = 1000 in scenario 2), and `REQUEST_INFO` does **not** increment `review_round`.

## Step 7: Run tests and iterate — 2026-09-03T02:39:00.000Z

Verified genuine: all 8 rounds ran the full 289s, collected all 144 tests, released their ports cleanly, and no `Terminated` appears in the log — the simultaneous finish is just 8 identical workloads launched at once, not SIGTERM reaping.

## Summary

**Iterations run: 1.** The task was already green; the first 8-round parallel sweep passed clean, so no diagnostic protocol steps were triggered.

**Sweep evidence** (`workspace/implementation/results.1.json` … `results.8.json`, all present and non-empty, ~48 KB each):

| Round | passed | total | failed | errors | skipped |
|---|---|---|---|---|---|
| 1–8 | 144 | 144 | 0 | 0 | 0 |

Union of failing tests across all 8 rounds: **empty**. No flakiness surfaced — no test passed in one round and failed in another.

- **Tests deleted:** none. No test failed either sub-check of STEP 1, because no test failed at all.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

**Integrity checks performed** (since I made no changes, I confirmed the passing state is legitimate rather than manufactured):

- No `pytest.mark.skip` / `xfail` anywhere in `test_suite/` — the only grep hit for "skip" is prose in a docstring at `test_suite/test_14_errors_part_a.py:531`, and `skipped=0` in every round confirms it.
- Storage is in-memory only. `workspace/implementation/store.py` holds 13 plain dict collections with a `reset()` on construction; no SQLite, no `json.dump`, no `/tmp` cache, no pickle/shelve. Nothing is seeded, preloaded or hardcoded, so each `start.sh` re-invocation wipes all state — which is what makes `--isolation per-test-server` meaningful here.
- `workspace/implementation/start.sh` runs `exec python3 app.py` in the foreground on `$PORT` with no forking, so the runner's per-round claimed port is honored and rounds don't collide.

The artifact is in a clean exit state: 144/144 across 8 concurrent rounds with no intervention required.

**Orchestrator independent re-verification (per prior known failure mode: a Step 7 agent claiming a clean sweep with no artifacts on disk).** I re-checked the artifacts myself rather than trusting the report: all 8 `results.{1..8}.json` exist, dated 02:32, ~48.5 KB each, and parsing each one's summary gives `passed=144 failed=0 errors=0 skipped=0 total=144`. `grep -c Terminated workspace/sweep.log` → 0, and the log tail shows a normal per-round completion (`Results: 144/144 passed`, `Duration: 289.3s`) with orderly port-registry releases. The sweep genuinely ran and genuinely passed.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T02:40:00.000Z

Skip condition met exactly as the skill defines it: Step 7 exited on the **first** 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. With an empty `<step_7_diff>` there is no fix site for Step 8 to trace an edit to, and the skill's HARD SCOPE rule forbids any PRD edit that does not trace to a Step 7 diff item, so spawning the subagent could only produce out-of-scope edits. No `PRD_FINALIZED.md` is produced; Step 9 therefore takes `workspace/PRD.md` as its source. Decision made autonomously by the orchestrator per the AUTONOMY directive.

## Step 9: Complete PRD — 2026-09-03T02:58:00.000Z

Structure verified: 507 lines, all 5 sections, 44 endpoint rows, 64 error rows, ends on the complete §5 table.

## Summary

- **Source**: `workspace/PRD.md` (507 lines, 103,495 chars) → **`workspace/PRD_COMPLETED.md`** (507 lines, 109,560 chars); **char delta +6,065**, line count unchanged (all edits are in-paragraph inserts; no new sections, no new paragraphs, no new table rows).
- **Counts**: 27 ambiguity-pins, 1 mismatch-revision, across 26 touched paragraphs.
- Every error identifier newly referenced in prose already exists in the §5 catalogue (verified programmatically).

### Changes

- §2.3 — insert — ambiguity — list ordering ties on `created_at` (common, since timestamps come from the logical clock) are broken by insertion order — `core.py:305-307`, `views.py:94`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `core.py:268-285`
- §2.3 — insert — ambiguity — an out-of-vocabulary enum filter value is `ERR_INVALID_REQUEST`; undeclared query params are ignored, not refused — `core.py:289-302`
- §2.4 — insert — ambiguity — the "same values" test excludes `version`/`updated_at`/`compliance_evaluated_at`, and a row touched twice in one request is versioned once — `domain.py:29,42-64`
- §2.5 — insert — ambiguity — clock accepts a backwards move and a bare `YYYY-MM-DD` (midnight UTC); `current_utc` is the sole `data` field — `views.py:1757-1762`, `store.py:94-99`
- §2.6 — insert — ambiguity — multi-reference payloads resolve in declaration order (order given per endpoint) — `views.py:333-334,580-581,660-664,1205-1215,1638-1639`
- §2.6 — insert — ambiguity — a field supplied as JSON `null` is treated exactly as omitted — `core.py:209-213`, `views.py:117-120`
- §2.7 — insert — ambiguity — ratios are emitted as JSON numbers, so `0.9000` serialises as `0.9` — `core.py:41-49`
- §3.1 — insert — ambiguity — each share fraction must lie in [0,1] as a schema bound (`ERR_INVALID_REQUEST`) before the unity sum is tested — `views.py:182-184`
- §3.1 — revise — **mismatch** — `home_state` is checked only as a non-empty string, never for two-letter length — `views.py:289`
- §3.2 — insert — ambiguity — `attrition_threshold_pct` out of (0,1] is `ERR_INVALID_REQUEST` — `views.py:321`
- §3.2 — insert — ambiguity — `SUBMIT`'s block-existence precondition is tested after the OPEN gate and yields `ERR_INVALID_STATE`; `REVISE` is not posture-gated — `views.py:407-418`
- §3.3 — insert — ambiguity — no uniqueness constraint on (tournament, team); repeat registrations are independent rows — `views.py:576-611`
- §3.4 — insert — ambiguity — a whitespace-only `chaperone_name` counts as absent — `views.py:819`
- §3.4 — insert — ambiguity — entry lower bounds (`occupant_count`≥1, `room_index`≥1, `minor_occupant_count`≥0) are schema checks → `ERR_INVALID_REQUEST` at check 9 — `core.py:222-227`
- §3.5 — insert — ambiguity — a `RECONCILING`/`SETTLED` event refuses cancellation with `ERR_INVALID_STATE`, after the booking's own source-state test — `views.py:915-916`
- §3.6 — insert — ambiguity — `decision_note` is optional on `REQUEST_INFO`/`APPROVE`/`DENY` and sticky when omitted; `START_REVIEW` never records one; `APPROVE` does — `views.py:1130-1143`
- §3.6 — insert — ambiguity — `RESUBMIT`'s `justification` is optional; omitting it keeps the stored one and still advances `review_round` — `views.py:1178-1180`
- §3.7 — insert — ambiguity — both close-booking preconditions (posture, ≥1 signed contract) yield `ERR_INVALID_STATE`, posture first — `views.py:243-253`
- §3.7 — insert — ambiguity — a report filed once `rebate_status` is past `ACCRUED` restates `actualized_room_nights` only — `views.py:961-969`
- §3.8 — insert — ambiguity — `DISPUTE`'s `dispute_note` is optional and sticky — `views.py:1560-1561`
- §3.8 — insert — ambiguity — `RELEASED → SETTLED` is re-evaluated only for blocks carrying a booking the resolution actually moved; manual release and the close sweep never re-evaluate it — `domain.py:353-358,513-526`
- §3.8 — insert — ambiguity — the remittance amount bound outranks the no-partial-out-of-`DISPUTED` rule — `views.py:1591-1599`
- §3.9 — insert — ambiguity — complaint filing is not posture-gated; team scope bites only when `registration_id` is named — `views.py:1216-1222`
- §3.9 — insert — ambiguity — triage of a `SETTLED` event answers `ERR_INVALID_STATE` — `views.py:1284-1285`
- §3.9 — insert — ambiguity — adjudication is not posture-gated — `views.py:1314-1320`
- §3.9 — insert — ambiguity — remedy structural and route-vocabulary checks are enforced on `DISMISS` too — `views.py:1331-1354`
- §3.9 — insert — ambiguity — distribution `tournament_id` supplies the shares and is never cross-checked against the source invoice's contract; creation is not posture-gated — `views.py:1636-1658`

Notable non-changes: the §2.11 rejection ladder, all 44 role lists, all 64 error/status pairs, and every calculation formula (roster occupancy variants, attrition thresholds and both shortfall clampings, penalty tiers, tiered/percent/flat rebate lines, admin-fee tiers, truncate-plus-remainder split) already matched `implementation/` exactly. The only impl behaviors left unmentioned are the non-domain `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED` handlers in `app.py:26-34` for unrouted paths — documenting them would require adding §5 rows, which the 64-row constraint forbids.

**Orchestrator verification:** independently confirmed `PRD_COMPLETED.md` is 507 lines / 109,560 chars, carries exactly the five top-level sections at the same line offsets as `PRD.md`, and ends on the complete final §5 row (`ERR_COMPLAINT_SUBJECT_MISSING | 422`) — no truncation.

## Pipeline complete — 2026-09-03T02:59:00.000Z

All nine steps done (Step 8 legitimately skipped). Final artifact state: scaffold trio + `worklog.md` + `test_helpers/` (9 modules) + `test_suite/` (conftest + 19 files, 144 tests) + `workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/, sweep.log, results.1-8.json}`. Benchmark verdict: **144/144 tests passing in all 8 concurrent sweep rounds, with zero test deletions and zero post-generation fixes to either the test artifact or the implementation.**
