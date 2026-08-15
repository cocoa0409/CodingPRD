# Worklog — task_2033_rodeo_event_production_contestant_entry

## Step 2: Generate Scaffold — 2026-08-15T09:09:00.000Z

Scaffold generation complete. All three artifacts are written and validated under `/home/ubuntu/github/CodingPRD/tasks/task_2033_rodeo_event_production_contestant_entry/` — generated purely from the scenario text plus the skill spec (no sibling tasks inspected).

**Files produced**
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys): 14 entities, 10 state machines, 6 calculations, 27 ordered validations, 51 endpoints, 27 errors, 6 roles, 1 OCC concurrency rule
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key; 18 instances, 2 per each of the 9 Difficulty Rules
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key; 42 full instances + 11 `excluded_because:` stubs across all 9 claim-extraction-guide sections

**Design highlights (complexity profile: Quota/allocation primary + Pricing engine secondary; flat topology; cyclic state shape; peer_roles)**
- Dual-variant calcs on different domains: Payout PROVISIONAL (RECORDED+VERIFIED) vs FINAL (VERIFIED-only); StockContract settlement day-rate vs per-out bases with pinned `max()`, tie → DAY_RATE
- Combinatorial formulas in two modes: tiered payout with tie-splitting and residual-to-last-place (mode a); per-entry fee split with pinned rounding order (mode b — fees 2005/2030 yield 2350 per-entry vs 2351 aggregate, computed and pinned as literals)
- Cyclic machines on different entities: StockAnimal AVAILABLE→DRAWN→COMPETED→AVAILABLE with inclusive MAX_OUTS=3 auto-retire; Entry DRAWN→TURNED_OUT→ENTERED re-entry loop; RunResult VERIFIED↔AMENDED with full compensation
- Depth-3 cascades from different triggers: vet INJURED_TURNOUT report → animal → assignment release + medical turn-out → purse recompute; contestant suspension → DRAWN_OUT + slot/animal release → purse recompute
- Priority conflicts on different category pairs: state vs business_temporal (entry create), business_safety vs business_referential (reride)
- Boundaries on different metrics/endpoints: inclusive ticket capacity (100th seat OK, 101st ERR_CAPACITY_EXCEEDED) and empty-go-round pool rollup (average 34008 = 52320 − 18312)
- Temporal overlap with different interval semantics: half-open arena adjacency allowed vs 45-minute buffered judge travel conflict
- Compensating invariants on different quantities: purse money conservation across create/cancel; seat inventory across purchase/refund
- All formula-derived asserts are pre-computed literals; all selectors deterministic (created_at ASC → card_number ASC for entries, tag_number ASC for animals, verified_at ASC for tie remainders — no id/random usage anywhere); logical clock endpoint with the mandated `2026-08-01T00:00:00Z` default

**Validation results**
- `scaffold_lint.py`: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (51 endpoints, 14 entities, 18 §1.8 + 42 §1.9 instances, 770 calls scanned)
- Additional scripted audits: 71 instance names unique across both files; zero unbound `${var}` placeholders; zero forbidden concurrency vocabulary; all 27 error codes referenced by ≥1 instance; scenario field verbatim; response envelope fixed block verbatim; all roles carry `identity:` (Contestant/Judge entity-backed, rest opaque).

## Step 3: Copy Shared Files — 2026-08-15T09:10:00.000Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md (bash, no subagent).

## Step 4: Generate PRD — 2026-08-15T09:26:00.000Z

PRD generation complete and all three hard contracts verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2033_rodeo_event_production_contestant_entry/workspace/PRD.md`

**Structure:** §1 Introduction (2 paragraphs, business-context angle); §2 with 9 subsections (RBAC with per-role identity translation, verbatim §2.2 response envelope, pagination, the logical clock, common resource properties incl. the immutable-VetReport exception, per-entry rounding discipline, cross-entity cascades, an 18-step validation-order pipeline, and single-endpoint OCC); §3 with 7 workflow subsections (production setup → entries/fees → stock/welfare → judges/results → the draw → ticketing/performances → purse/payout/settlement); §4 with a 51-row 4-column endpoint table; §5 with a 27-row 2-column error table. The document ends at §5 with no audit footer.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 84 required (incl. id/created_at/updated_at/version), 84 present, 0 missing
- endpoints[].request_body: 55 required, 55 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS (verified in two passes)

Rule coverage check:
- validations[] with priority: 27 checked, 27 expressed in prose (full ordered pipeline in §2.8 plus per-endpoint orderings in §3.2/§3.5), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (draw execution + expected_rodeo_event_version + ERR_STALE_VERSION/412 all named, stale-version framing only), 0 missing
- state_machines[].transitions: 47 checked across 9 machines, 47 fully expressed (from/to states, preconditions with error_ids where scaffolded, all side-effect cascades), 0 missing
- calculations[]: 6 checked (entry_fee_split with the 2005/2030 worked figures, purse_and_places with tie-split and residual pins, average_aggregate, contractor_settlement with tie→DAY_RATE, welfare_out_threshold with inclusive 3-out boundary, ticket_capacity_check), 6 fully expressed, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 51 endpoints checked, all side effects and validation scopes expressed, 0 missing
- entities[].fields[] structured content: all types, ranges, defaults, initial values, and computed derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (VERIFY/VOID dual source states, 3-state rodeo cancel, 3-state vet RETIRE, VOLUNTARY/MEDICAL turn-out, 1–4 place percentage arrays, PROVISIONAL/FINAL variants, DAY_RATE/PER_OUT bases, AVAILABLE/COMPETED/DRAWN injury sources), 8 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 535
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 is byte-identical to `section-2.2-response-structure.md`; all enum/state values (including `RELEASED` and `RE_ENTER`, added in a repair pass) and all 27 error IDs appear; a fuzzy-word scan (approximately/about/roughly/conservatively/etc.) is clean; §4 row count and method/path pairs match the scaffold exactly; §5 status codes match the scaffold. The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-15T10:05:00.000Z

Done. Task 2033 test infrastructure and suite are fully generated and audited.

## What was built

**`test_helpers/`** (Stage 1) at `/home/ubuntu/github/CodingPRD/tasks/task_2033_rodeo_event_production_contestant_entry/test_helpers/`:
- `types.py` — 14 entity TypedDicts + 17 status/role enums; `VetReport` correctly omits `updated_at`/`version` (append-only per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (all 39, `/api`-prefixed)
- `api_errors.py` — all 27 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus payout helpers `place_lines_for` / `place_line_for`
- `factories.py`, `constants.py` (600 sanction / 12% retention / 30% average share / 3-out welfare limit / 45-min judge buffer), `test_users.py` (opaque shared constants + mandatory `make_contestant_headers`/`make_judge_headers` entity-backed builders)
- `fixtures.py` — 5-tier composites: `setup_entries_open`, `setup_draw_locked`, `setup_drawn`, `setup_in_progress`, `setup_completed_rodeo`, `setup_finalized_payout`, `drive_go_round`, `setup_riders_with_mixed_results`, plus granular creators; `execute_draw` self-fetches the current event version for OCC

**`test_suite/`** (Stage 2): `conftest.py` + 11 test files, **78 tests** — every one ending with exactly one verbatim `Design: Difficulty/<rule>/<instance>` or `Design: Corner/<section>/<instance>` tag.

## Audit results (all green)

- **Coverage**: all 18 difficulty instances × ≥2 tests; all 42 non-stub corner instances × ≥1; all 10 `excluded_because:` stubs untranslated with cross-references verified to resolve; zero orphan tags; zero dual-tagged tests
- **Citations**: every docstring's quoted PRD passage survives a normalized verbatim grep of `PRD.md` (0 misses across ~90 quoted spans)
- **Hygiene**: no `skip`/`skipif`/`xfail`, no "scaffold" references in generated code, `py_compile` clean, `pytest --collect-only` collects 78 tests

## Notable PRD-adjudication decisions

- **Version start value**: PRD §2.5 pins "+1 per mutation" but never "starts at 1", so `contestant_version_increments_on_each_mutation` and the creation-defaults test assert relative increments (`v+1`) and integer presence rather than absolute `== 1` — the instance's absolute-value phrasing fails the two-reader test.
- **Empty go-round pool lines**: asserted `go_round_pools == [{go_round: 2, pool_cents: 18312}]` per the pre-audited corner instance, justified by §3.7's "its pool rolls into the average" (the pool ceases to be a go-round pool).
- **`contract_activate_requires_rodeo_pre_lock`** kept as `ERR_RODEO_NOT_OPEN`: §2.8 item 7 maps posture-gate failures to that error and §2.8 item 6 scopes `ERR_INVALID_STATE` to the resource's own state, so both readers converge.
- All pinned arithmetic (purse 104640/52320, pools 73248/18312/34008, tie splits 36624/15696/3334-3333-3333/1428-1429-1429, settlement 100000 DAY_RATE vs 12000 PER_OUT) verified against §2.6/§3.7 formulas before encoding.

## Step 6: Generate implementation — 2026-08-15T10:05:00.000Z

Python + Flask implementation written to `workspace/implementation/` (start.sh, requirements.txt, app.py, db.py, errors.py, response.py, middleware.py, util.py, services.py, routes/ with 13 modules). In-memory store starts empty on every boot (no seeding); logical clock defaults to `2026-08-01T00:00:00Z` and moves only via POST /api/_clock/set_current_utc.

Fidelity notes (PRD-over-scaffold applied):
- Envelope: meta{api_request_id, api_request_timestamp} + response_type + data; list pagination fields limit/offset/total_count/has_more (defaults 10/0, 1..100); error body data{error_id, message}.
- Validation pipeline ordered per PRD §2.8: auth(401) → forbidden/ownership(403) → path 404 → body-FK 404 → shape(400) → state(409 ERR_INVALID_STATE) → posture(409 ERR_RODEO_NOT_OPEN) → window/standing → animal/contract gates → uniqueness/dups → conflicts → draw integrity (ERR_GO_ROUND_INVALID 422 before ERR_STALE_VERSION 412, OCC always last).
- Fee ledger per-entry rounding (sanction 600 flat, retention round_half_up(12%), contribution residual); refund rules: CANCEL_ENTRY keeps sanction, TURN_OUT MEDICAL refunds contribution only, VOLUNTARY forfeits, DRAW_OUT/suspension/rodeo-cancel full refund incl. sanction; re-entry re-charges (double contribution intended).
- Draw: pool = ENTERED ∪ DRAWN (+ this round's prior waitlisted via supersede), sorted created_at ASC → card_number ASC; round-robin into SCHEDULED perfs by starts_at ASC with per-performance_slots per go-round; rough stock 1:1 in tag_number ASC from AVAILABLE + welfare<3 + ACTIVE-contract pool (supersede-freed animals rejoin); atomic ERR_INSUFFICIENT_STOCK with zero mutation.
- Payouts: pool_g = round_half_up(purse*0.70/go_rounds); empty go-rounds roll into average (residual pinned); last paid place takes pool residual; ties split combined places equally round-half-up with leftover to earliest verified_at (created_at tiebreak, never id); average eligibility = QUALIFIED in every go-round; PROVISIONAL ranks RECORDED+VERIFIED, FINAL ranks VERIFIED only; FINALIZE recomputes under FINAL; SETTLE disburses, settles ACTIVE contracts (max(day-rate × distinct UTC performance days, per-out × COMPLETED outs), tie → DAY_RATE), and rolls zero-eligible average pools into rodeo.unclaimed_purse_cents.
- Welfare counter invariant == count of VERIFIED results; verify: DRAWN→COMPETED then auto-release (<3) / auto-retire (≥3, inclusive); amend compensates (count−1, animal back to DRAWN incl. from RETIRED, assignment COMPLETED→PENDING, entry COMPETED→DRAWN).
- VetReport immutable (id + created_at only); injury/retire on a DRAWN animal releases its PENDING assignments and turns out their entries MEDICAL with contribution refund + vet_report_id; CLEARED valid only from INJURED.
- Every cascade-touched resource gets updated_at refreshed and version +1; stored payouts go stale until recomputed (never patched in place).

Verification: two smoke suites (main flow + cascades/edges) run green against `bash start.sh` on a fresh process; fresh-boot contract (empty store, clock endpoint, PORT/0.0.0.0 foreground exec) confirmed.

## Step 7: Run Tests and Iterate — 2026-08-15T10:15:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 78 tests/round).

**Iteration 1** — 75/78 in every round; union of 3 deterministic failures:
- `test_empty_go_round_pool_rolls_into_average_pool` (test_09): asserted `go_round_pools == [{go_round: 2, pool_cents: 18312}]` (empty round's line removed). STEP 1b unique-derivability collapse: §3.7 states both "the pools are recorded in `go_round_pools` as one `go_round`/`pool_cents` pair per go-round" (all rounds recorded) and "its pool rolls into the average" (empty line vanishes); both readings are PRD-faithful. STEP 1c split applied: kept the verbatim-covered `purse_cents == 52320` and `average_pool_cents == 34008` assertions, relaxed the divergent exact-list assertion to membership of the non-empty round's line (`{"go_round": 2, "pool_cents": 18312} in go_round_pools`), which both readings admit.
- `test_settlement_computes_both_bases_and_pays_max` + `test_settle_disburses_payout_and_settles_contract` (test_10): setup failed with `ERR_JUDGE_NOT_ASSIGNED`. STEP 2 test bug: `_settled_rodeo` schedules two performances and the §3.5 draw slots entries round-robin (entry 2 → performance 2), but the judge was assigned only to performance 1, so §3.4's assignment gate correctly rejected entry 2's result. Fixed the fixture to assign the judge to both performances (buffered windows on distinct UTC days cannot conflict).

**Iteration 2** — all 8 rounds 78/78 passed, 0 failed, 0 errors. No implementation changes were required; both fixes were in the test layer.

## Step 8: Finalize PRD — 2026-08-15T10:22:00.000Z

The single-edit diff is confirmed. Here is the exit summary.

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_2033_rodeo_event_production_contestant_entry/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 336 lines, PRD_FINALIZED.md = 336 lines (0.0% delta — one in-place sentence revision, no lines added or removed).

### Changes

- **§3.7 (Purse Accounting, Payouts, and Settlement)** — **revise** — the sentence "the pools are recorded in `go_round_pools` as one `go_round` / `pool_cents` pair per go-round" was ambiguous between "one pair for each of the N go-rounds" and "one pair per non-empty go-round" (both PRD-faithful per Step 7's STEP 1b analysis of `test_empty_go_round_pool_rolls_into_average_pool`). Appended the clause ", with every go-round from 1 through the event's `go_rounds` recorded — including empty ones." to pin the implementation's behavior — `implementation/services.py:504` (`go_round_pools.append({"go_round": g, "pool_cents": pool_g})` runs unconditionally for every `g in range(1, n_rounds + 1)`).

### Step-7 items disposition

- **test_09 (`test_empty_go_round_pool_rolls_into_average_pool`)** — genuine PRD silence → the one edit above.
- **test_10 (`test_settlement_computes_both_bases_and_pays_max` + `test_settle_disburses_payout_and_settles_contract`)** — pure test-fixture bug per Step 7 (STEP 2: judge assigned to only one of two performances; the §3.4 `ERR_JUDGE_NOT_ASSIGNED` gate and §3.5 round-robin behaved exactly as the PRD already specifies). No PRD edit — the PRD already determines this behavior uniquely.

### Per-edit pre-edit search log

**Edit 1 (§3.7 `go_round_pools` wording):**
- **(a) Subject:** what `go_round_pools` contains for an empty go-round (zero qualified ranked contestants).
- **(b) Impl paths enumerated and read:** (1) `implementation/services.py:493-519` — the construction loop in `compute_purse_and_places`: appends one pair per `g` in `1..n_rounds` regardless of emptiness, accumulates `non_empty_sum` only for non-empty rounds, computes `average_pool = purse - non_empty_sum`; (2) `implementation/routes/payouts.py:50, 60, 118` — all three storage sites (compute, recompute, finalize) store the list verbatim with no filtering; (3) `implementation/services.py:635` — `settle_rodeo_cascade` reads only `average_pool_cents`/`place_lines`, never inspects `go_round_pools` contents, so unaffected. Also cross-checked the two test sites touching the same field: `test_suite/test_09_payouts.py:209` (2-round event, round 1 empty — relaxed membership assertion, consistent with the pin) and `test_suite/test_09_payouts.py:326` (single-round event, exact-list equality `[{"go_round": 1, "pool_cents": 10000}]` — fully compatible with "one pair per go-round 1..N", since N=1 and round 1 is non-empty there).
- **(c) Wording adjustment:** the added clause is scoped strictly to recording completeness ("every go-round from 1 through the event's `go_rounds` recorded — including empty ones") and says nothing about pool values, ordering, or the average computation, so it cannot mis-describe the verbatim-storage paths or the settlement path. No further softening was needed; the original sentence's "one pair per go-round" phrasing is retained and merely disambiguated.

## Step 9: Complete PRD — 2026-08-15T10:45:00.000Z

Done. `PRD_COMPLETED.md` has been produced at `/home/ubuntu/github/CodingPRD/tasks/task_2033_rodeo_event_production_contestant_entry/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`.

## Summary

**Source vs output**: `PRD_FINALIZED.md` 336 lines / 50,184 bytes → `PRD_COMPLETED.md` 337 lines / 54,467 bytes (char delta +4,239 chars; +4,283 bytes due to multibyte em-dashes).

**Counts**: 31 ambiguity-pins, 7 mismatch-revisions (38 changes total; all inline inserts/revisions, no new sections).

**Changes** (section — kind — class — what — impl ref):

- §2.2 — insert — ambiguity — undefined path/unsupported method → `ERR_NOT_FOUND` 404; malformed/non-object JSON body → `ERR_VALIDATION` 400 — app.py:20-30, util.py:29-35
- §2.3 — revise — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; list ties on `created_at` broken by creation order — util.py:96-118, services.py:74-75
- §2.4 — revise — ambiguity — clock set accepts any instant; monotonicity not enforced — routes/clock.py:12-19
- §2.5 — revise — ambiguity — `version` starts at 1 at creation — services.py:47-53
- §2.8 item 2 — revise — mismatch — removed the never-implemented "result's judge identity matching the caller (`ERR_FORBIDDEN`)" clause; pinned that action-level role checks and entry-ownership comparison run after path resolution (unknown path id → 404 first) — run_results.py:197-212, entries.py:143-167
- §2.8 item 7 — revise — ambiguity — enumerated all posture gates impl enforces (turn-outs DRAW_LOCKED/IN_PROGRESS; verify/amend and performance completion IN_PROGRESS; contract activation DRAFT/ENTRIES_OPEN) — entries.py:196, run_results.py:114,236, performances.py:125, stock.py:100
- §2.8 item 12 — revise — ambiguity — card numbers unique per collection, contestants and judges independent — contestants.py:27-31, judges.py:30-32
- §2.9 — revise — mismatch — `expected_rodeo_event_version` is optional (check only when supplied); any version difference rejects, not just "advanced past" — rodeo_events.py:103-105,138-143
- §3.1 — revise — ambiguity — event creation and performance scheduling not gated on rodeo posture — rodeo_events.py:33-70, performances.py:32-81
- §3.1 — revise — ambiguity — `OPEN_ENTRIES` lacking event/performance → `ERR_INVALID_STATE` — rodeos.py:90-96
- §3.2 — revise — ambiguity — `TURN_OUT` restricted to EntryOffice or the contestant themself — entries.py:159-167
- §3.2 — revise — ambiguity — `RE_ENTER` likewise restricted (not CommitteeAdmin) — entries.py:159-167
- §3.2 — revise — ambiguity — no-op standing patch → `ERR_INVALID_STATE` — contestants.py:74-79
- §3.3 — revise — ambiguity — contract creation not posture-gated; `ACTIVATE` outside DRAFT/ENTRIES_OPEN → `ERR_RODEO_NOT_OPEN` — stock.py:25-54,99-105
- §3.3 — revise — ambiguity — animal registration not gated on contract status — stock.py:120-145
- §3.3 — insert — ambiguity — injury report valid only from AVAILABLE/COMPETED/DRAWN; retirement only from AVAILABLE/INJURED/DRAWN; else `ERR_INVALID_STATE` — vet_reports.py:82-95
- §3.4 — revise — ambiguity — judge `card_number` unique among judges; judge/contestant namespaces independent — judges.py:30-32
- §3.4 — revise — ambiguity — judge assignment not gated on rodeo posture or performance status — judges.py:67-109
- §3.4 — revise — ambiguity — result recording requires the assignment still `PENDING` (else `ERR_INVALID_STATE`) — run_results.py:104-110
- §3.4 — revise — ambiguity — `amendment_reason` required (missing/empty → `ERR_VALIDATION`); omitted amend fields retain stored values; discipline rules validated against merged payload — run_results.py:213-220,255-275
- §3.4 — revise — mismatch — amend returns animal to `DRAWN` from COMPETED, **AVAILABLE**, or RETIRED (PRD omitted AVAILABLE, the common post-auto-release source) — services.py:402-407
- §3.5 — revise — ambiguity — `START_RODEO` precondition failure → `ERR_INVALID_STATE` — rodeos.py:97-104
- §3.5 — revise — mismatch — draw supplies `go_round_number` and *optionally* `expected_rodeo_event_version` — rodeo_events.py:96-143
- §3.5 — revise — mismatch — draw pool also includes entries still `DRAWN` from earlier go-rounds (plus the go-round's prior waitlisted on supersede), not just `ENTERED` — services.py:223-236
- §3.5 — revise — ambiguity — performance `starts_at` ties break by creation order — services.py:245-250
- §3.5 — revise — ambiguity — animal `tag_number` ties across contracts break by registration order — services.py:298
- §3.5 — revise — ambiguity — within a draw the stock gates only shrink the pool (shortfall → `ERR_INSUFFICIENT_STOCK`); `ERR_ANIMAL_NOT_ELIGIBLE`/`ERR_CONTRACT_NOT_ACTIVE` come from direct selection (re-ride) — services.py:275-304, draw_assignments.py:73-89
- §3.5 — revise — mismatch — waitlisting occurs in *any* go-round (a previously DRAWN entry finding no slot moves to WAITLISTED), not only the first — services.py:339-342
- §3.5 — revise — ambiguity — re-ride on a TIMED assignment → `ERR_VALIDATION`; non-PENDING → `ERR_INVALID_STATE` — draw_assignments.py:62-72
- §3.6 — insert — ambiguity — ticket sales not gated on performance status or rodeo posture; capacity is the only check — ticket_orders.py:14-56
- §3.6 — revise — ambiguity — `COMPLETE_PERFORMANCE` outside IN_PROGRESS → `ERR_RODEO_NOT_OPEN` — performances.py:123-130
- §3.7 — revise — ambiguity — `COMPLETE_RODEO` checks performances first (`ERR_INVALID_STATE`), then unverified results (`ERR_RESULTS_PENDING`) — rodeos.py:105-123
- §3.7 — revise — ambiguity — any compute leaves the payout PROVISIONAL (recomputing a FINAL payout demotes it); DISBURSED payout rejects recomputation with `ERR_INVALID_STATE` — payouts.py:38-41,57-65
- §3.7 — revise — mismatch — zero-eligible average rolls its entire **average pool** (not "the entire purse") to `unclaimed_purse_cents` — services.py:631-637
- §3.7 — revise — ambiguity — fewer ranked contestants than `payout_places` → leading percentages of the event's schedule apply — services.py:424-439
- §3.7 — revise — ambiguity — equal metrics keep creation order of underlying results — services.py:503,537
- §3.7 — revise — ambiguity — average ties use each contestant's earliest-verified in-scope result for leftover ordering — services.py:535
- §3.7 — revise — ambiguity — ties recognized only within paid places; straddling ties pay only contestants inside the boundary — services.py:441-444

Tests were used only as cross-reference greps (never as authority); all pins trace to `implementation/` line references above.
