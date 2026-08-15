# Worklog — task_1695_congregation_youth_program_mission_trip

## Step 1: Create Task Directory — 2026-08-14T08:45:00.000Z

Task directory `tasks/task_1695_congregation_youth_program_mission_trip/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker; Step 1 treated as DONE per instructions (no index scan, no writes outside this directory).

## Step 2: Generate Scaffold — 2026-08-14T10:18:00.000Z

All three scaffold artifacts are generated, linted clean, and audited. No sibling task directory was inspected — the design is purely from the scenario description and the skill specification.

### Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1695_congregation_youth_program_mission_trip/`)

- **SCAFFOLD.yaml** (1828 lines) — §1.0–§1.7 only, no design keys. Scenario verbatim; `domain_name: congregation-youth-mission-trips`; `api_prefix: /youth-ministry`.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (1149 lines) — 25 instances: all 9 rules with 2–3 instances each (dual_variant 2, combinatorial 3 covering modes a/b/c, non_linear_state_machine 3, transitive_cascade 2, priority_pair 3 with three distinct error-category pairs, boundary 3, cross_entity 3, temporal_overlap 3 with three distinct interval semantics, compensating_invariant 3).
- **SCAFFOLD_CORNER_DESIGN.yaml** (1447 lines) — 56 instances (47 active + 9 `excluded_because` stubs) across all 9 claim-extraction sections, including full 61-error triggerability coverage.

### Difficulty profile (maximized per request)

- **14 entities, 63 endpoints, 61 error codes, 12 calculations, 12 state machines, 2 OCC concurrency rules** — deliberately past the Expert band (§0.4 guidelines) as requested.
- **Archetype**: compliance/audit + quota/allocation; flat topology; segregation-of-duties role model (scholarship approver≠disburser by stored user id; reviewer≠guardian); 4 complexity layers (OCC, cascading side effects, dual-variant calc, ops-run clock sweeps).
- **Flagship mechanics**: provisional-vs-final cost share (divides by planned capacity vs confirmed headcount, with round-then-sum remainder waterfall by `created_at` — lock can downgrade PAID_IN_FULL); gross-vs-net fundraising credit with per-channel fees; need_score with per-component caps and state-filtered sibling sets; scholarship award min-chain with pinned evaluation order; registration parallel dimensions (registration_status × payment_status with DELINQUENT cure cycle); cyclic ConsentForm reject→resubmit and ScholarshipApplication appeal loop; depth-3 trip-cancel cascade (Trip→Registration→Scholarship→Program fund) and depth-2 screening-flag cascade; three interval semantics (half-open lodging adjacency-ok, 45-min vehicle buffer, closed-date chaperone overlap); logical clock with mandatory default `2026-08-01T00:00:00Z` driving delinquency + screening-expiry sweeps.
- All formula-derived asserts are precomputed literals (verified by executing the formulas in Python: e.g., provisional 203010 vs final 230100; waterfall shares 233333/233334/233334; need 90 vs 30; award 76129; late fee 4000; barred_until 2029-06-14T00:00:00Z).

### Verification

- `scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (63 endpoints, 14 entities, 25 + 47 active instances, 1167 calls scanned, 0 violations.)
- Additional scripted audit beyond the linter: placeholder closure (every `${var}` bound by an earlier `captures:`), instance-name uniqueness across both files, grounds resolvability, error-code references, negative-test polarity, forbidden-vocabulary scan, and no `id`-based business ordering — all clean.
- Authoring-time fixes baked in: removed a dead `ERR_ITINERARY_ITEM_NOT_FOUND` (no endpoint could raise it), aligned lock-roster gate order with validation priorities (empty-roster moved to referential so the ratio check passes vacuously at 0 youth), and made donation creation account-state-gated so `ERR_ACCOUNT_CLOSED` is independently triggerable.

## Step 3: Copy Shared Files — 2026-08-14T10:20:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1695_congregation_youth_program_mission_trip/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:30:00.000Z

Note: the Step 4 subagent's first invocation returned prematurely (context enumeration only, no file written); it was resumed via SendMessage and completed the PRD plus all hard-contract checks.

Done. The PRD is written and all three hard contracts pass.

### Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1695_congregation_youth_program_mission_trip/workspace/PRD.md` — **383 lines**

**Structure:** Title + 5 top-level sections: §1 Introduction (3 paragraphs); §2 Global Specifications with 9 domain-derived subsections (RBAC with per-role identity translation, verbatim §2.2 response envelope, pagination, logical clock, common resource properties/version semantics, money/precision, OCC, a 12-step validation-priority list, flat collections & rollup reconciliation); §3 Business Logic with 9 lifecycle-grouped subsections (program/policy, trip lifecycle incl. branching cancel cascade, participant/registration/consent intake, payments/donations/fundraising credit, scholarships with pinned award min-chain, cost shares & delinquency sweeps, withdrawal/dismissal discipline, chaperone screening & assignments, itinerary & lodging); §4 endpoint table (4 columns, 63 rows — matches scaffold's 63 endpoints); §5 error catalogue (2 columns, 61 rows — matches scaffold's 61 error codes).

**Hard-contract verification results:**

- **Contract 1 — Field-Name Coverage: PASS.** 127 required tokens (all `entities[].fields[].name`, all endpoint `input`/query identifiers, common fields, pagination params); 127 present in backticks, 0 missing. Two initial gaps (`fundraising_account_id`, `DISMISSED`) were repaired in-place and the check re-run to empty diff.
- **Contract 2 — Rule Coverage: PASS.** 12 state machines / 67 transitions, 12 calculations, 12 validations, 2 OCC rules, 61 error ids inventoried. 30 targeted spot-checks on the highest-risk rules all present: both OCC rules (write capability + `expected_program_version`/`expected_trip_version` + exact error id + HTTP 412, plus the "no other endpoint takes a version field" scope note), the 12-step validation priority ordering with worked examples (fund-exhausted before award-zero; registration-state error before account-closed), all pinned calculation details (round-then-sum waterfall, donation-fee rounding order, strict `>` sweep boundary, `max(2500, 5%)` late fee, need-score band values/caps, four-term award min-chain, conserved fund triple, inclusive screening boundary, waitlist tie-breaks with id excluded, 45-minute vehicle buffer, half-open room overlap, closed-interval chaperone overlap, 730-day screening/bar durations, clock default `2026-08-01T00:00:00Z`), and branch asymmetries (empty DRAFT-cancel cascade, dismissal retaining `DISBURSED` scholarships, locked-trip withdrawal keeping final shares). All 40 state enum values and all 61 error ids appear in §2/§3 prose.
- **Contract 3 — §3 Path Purity: PASS.** 685 backtick tokens scanned in §3; 0 tokens starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens.

§2.2 was emitted byte-identical to the fixed block (verified `req_RANDOMALPHANUM123456` and `"data": { }` markers intact). The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Steps 5+6: Generate Unit Tests + Implementation (concurrent) — 2026-08-14T11:25:00.000Z

Both subagents were launched concurrently in a single message; physical isolation held (implementation agent had no access to test_helpers/ or test_suite/, which did not yet exist when it started).

### Step 5 summary (unit tests) — verbatim:

Generation complete. Both stages are on disk and all audits pass.

#### What was generated

**`test_helpers/`** (9 files): `types.py` (14 entity TypedDicts + 16 status/role enums), `api_client.py` (all 63 `/youth-ministry` endpoints), `api_errors.py` (all 61 error IDs with the §5 HTTP map registered into the framework), `assertions.py` (per-entity shape checks + `assert_fund_conserved` + `assert_same_instant`), `factories.py`, `constants.py` (fee/late-fee/need-score/ratio constants), `test_users.py` (opaque role constants + `make_chaperone_headers` entity-backed builder), `fixtures.py` (composite chains: open trip, submitted/approved/confirmed registration, cleared chaperone, confirmed assignment, lock-ready and in-progress trip setups).

**`test_suite/`** — `conftest.py` + 15 concern-grouped files, **97 tests**: 50 difficulty-tagged (25 instances × 2) + 47 corner-tagged (every non-stub instance × 1). The 9 `excluded_because:` stubs were not translated; their difficulty cross-references all resolve.

#### Audit results (all green)
- **Tag audit**: every test has exactly one `Design:` line; every tag resolves to a real instance `name:`; 25/25 difficulty instances at ≥2 tests; 47/47 non-stub corner instances at ≥1; zero stub tags used.
- **PRD citation audit**: all 97 docstrings contain a ≥8-word span that greps verbatim (whitespace-normalized) in `workspace/PRD.md`.
- **Hygiene**: no `skip`/`skipif`/`xfail`, no scaffold references in comments/docstrings, all files compile, all imports resolve, `pytest --collect-only` collects 97 cleanly.

#### Judgment calls (PRD-first filter applications)
1. **`screening_expiry_sweep_at_exact_expiry_cascades`** — the corner recipe's trip dates (end 2027-06-16) contradict the PRD's expiry-removal filter (trip end instant must be ≥ `expires_at` 2028-07-31). I repaired the setup dates to 2028-07-28..2028-07-30 (end instant exactly `expires_at`, boundary-inclusive per §3.8) so the asserted `AUTO_SCREENING` removal is PRD-derivable; asserted literals unchanged.
2. **Version assertions are relative** (`v+1` per mutation), never absolute `== 1` — PRD pins "increments by exactly 1 on every mutation" but never names the initial value.
3. **Two arms dropped as non-derivable** (instances still emitted with their derivable arms): rejection of a client-supplied `version` field (PRD never says extra fields are rejected), and rejection of `vehicle_code` on a non-TRAVEL item (PRD says it "otherwise defaults to empty").
4. **Clock-stamped domain datetimes** (`posted_at`, `cleared_at`, `expires_at`, `debriefed_at`, `barred_until`) are compared as parsed instants — PRD pins the three-fractional-digit rendering only for `created_at`/`updated_at`/`api_request_timestamp`.
5. **1:1 fundraising-account read** tolerates list-of-1 or object payloads (PRD doesn't pin the shape); the rule-bearing account fields are asserted either way.
6. **Waitlist-head and remainder-waterfall tests advance the logical clock between registration creates** — with the frozen default clock, all `created_at` values tie and the asserted orderings would not be uniquely derivable.
7. **Grade-bounds test creates participants as Guardian** — a ProgramDirector create without `guardian_user_id` would itself violate the explicit-guardian rule, contaminating the 201 arms.

### Step 6 summary (implementation) — verbatim:

Done. The complete implementation is in place and verified.

#### What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1695_congregation_youth_program_mission_trip/workspace/implementation/`:

- **start.sh** — executable, guarded dependency install (`python3 -c "import flask"` no-op check so per-test reboots skip pip), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- **requirements.txt** — flask>=3.0
- **app.py** — thin entry point importing the app and route modules (avoids the `__main__` double-import pitfall, which I hit and fixed by moving the Flask instance into `web.py`)
- **web.py** — Flask app, envelope-aware error handlers, auth (`X-User-ID`/`X-User-Role`, six roles), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, 1–100 clamp), 404 lookups with the exact per-entity error IDs
- **store.py** — empty-at-boot in-memory store (no seeding), logical clock defaulting to `2026-08-01T00:00:00Z`, per-request version-bump coalescing
- **util.py** — success/error envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), ISO-8601 parsing/normalization, Decimal `ROUND_HALF_UP` helpers, strict body validators (missing → `ERR_INVALID_REQUEST`, bad enum → `ERR_INVALID_ENUM`, bad ordering → `ERR_INVALID_DATE_RANGE`)
- **domain.py** — all 12 calculation rules (provisional share, final-share remainder waterfall, card fee pct-then-flat, gross/net fundraising positions, need score with pinned cap order, scholarship award min-chain, chaperone ceiling ratio, late-fee max(2500, 5%), payment-status rollup, lodging rollup, waitlist head selector, conserved fund triple), cascades (trip-cancel depth-3, withdraw/dismiss, screening FLAGGED/EXPIRED with AUTO_SCREENING removals), delinquency + expiry sweeps with idempotency flags
- **routes_core.py / routes_people.py / routes_money.py / routes_staff.py** — all 63 endpoints with the §2.8 validation priority order (auth → body → role → existence → ownership/SoD → state → OCC → safety → forms → temporal → constraint → fiscal)

#### Verification

Three exercise suites (171 assertions total) all pass on fresh boots via both `python3 app.py` and `bash start.sh`: envelope/pagination shape, RBAC matrix, guardian/chaperone ownership, SoD (reviewer≠guardian, disburser≠approver), both OCC surfaces (412), full trip lifecycle including the lock-roster gate chain in exact priority order (ratio → insurance → empty roster → emergency protocol → lodging beds → unpaid balances), capacity-fork waitlisting and head-of-line promotion, donation fees, apply-credit net-vs-gross split, scholarship approve/deny/appeal/disburse/rescind with fund conservation, delinquency sweeps (idempotent, strict-> boundary, two-fee case, DELINQUENT cure rules), screening expiry at the inclusive boundary with selective assignment removal, 45-minute vehicle buffer, half-open room overlap, closed-date chaperone trip overlap, dismiss/BARRED_FROM_FUTURE (730-day bar), and reboot-is-clean (empty store on every fresh process).

Key interpretation decisions (PRD-faithful): version starts at 1 and bumps on any representation change (§2.5), coalesced to one bump per entity per request; clock-stamped fields render the logical clock verbatim (whole seconds), while `created_at`/`updated_at`/`api_request_timestamp` use wall-clock with 3 fractional digits per §2.2/§2.5; the delinquency sweep runs A then B within one clock set, so a registration missing both deadlines collects two fees.

## Step 7: Run Tests and Iterate — 2026-08-14T11:45:00.000Z

Orchestrator verification: all 8 `results.{i}.json` files report `passed: 97 / 97, failed: 0`.

All 8 rounds pass 97/97 with an empty failure union. Exiting with the summary.

### Summary

**Iterations run:** 2 full 8-round parallel sweeps (plus one invalidated sweep — all 8 rounds collected 0 tests due to a transient `__pycache__` compile race on just-edited sources; a single-round probe passed 97/97 and the rerun sweep was clean).

**Tests deleted:** none.

**Round-1 failure union (3 tests, deterministic across all 8 rounds) and resolutions:**

1. **`test_01_program_basics_and_envelope.py::TestSystemMintedFields::test_server_minted_system_fields_on_create`** — `created_at` was wall-clock (`2026-08-14T...`), test expected the logical-clock default `2026-08-01T00:00:00Z`.
   - STEP 1a: PRD §2.4 covers verbatim: "The system never reads the wall clock... Before any operator sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."
   - STEP 1b: uniquely derivable — the prohibition is absolute and unscoped; corroborated by §3.3's waitlist tie-break ("ties broken by the participant's `created_at` ascending"), which is only reachable when `created_at` values can tie, i.e., when clock-stamped. A wall-clock implementation directly violates the sentence, so the divergent reader is not PRD-faithful.
   - STEP 3 fix in `implementation/`: **`util.py`** — replaced `_wall_timestamp()` with `_now_timestamp()` (stamps from `DB.clock_dt`, three fractional digits per §2.5/§2.2) used by all three envelope builders (`success_object`/`success_list`/`error_response`); **`store.py`** — `Store.stamp_created` and `Store.touch` now stamp `created_at`/`updated_at` via a new `_clock_stamp()` from the logical clock instead of the wall clock.

2. **`test_13_trip_cancel_and_dismissal.py::TestTripCancelDepth3Cascade::test_cancel_cascades_registration_account_forms_payments`** — `TypeError: 'Response' object is not subscriptable`.
   - STEP 1: cascade rule verbatim in PRD §3.2 (quoted in docstring), uniquely derivable.
   - STEP 2 fix in `test_suite/test_13_trip_cancel_and_dismissal.py`: `_cancel_cascade_setup` stored the raw `Response` from `api.confirm_registration` in `ctx["registration"]` (the `validate_success(...)` return was discarded); now stores `validate_success(...)`'s data dict. Pure test-code bug, assertion unchanged.

3. **`test_14_logistics_overlap.py::TestRoomBookingHalfOpen::test_same_room_code_at_other_site_and_rollup_total`** — `assert 25000 == 35000`.
   - STEP 1: PRD §3.9 covers verbatim ("`lodging_cost_total_cents` — the sum of `cost_cents` over `CONFIRMED` reservations"), uniquely derivable; the implementation was already correct (all three reservations accepted and summed).
   - STEP 2 fix in `test_suite/test_14_logistics_overlap.py`: the expected literal was a plain arithmetic error — setup costs are 10000 + 10000 + 5000 = 25000, not 35000. Corrected the literal; the asserted rule (cross-site same-`room_code` allowed + rollup over all CONFIRMED reservations) is fully preserved.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** `util.py` (`_now_timestamp` replaces `_wall_timestamp` in envelope builders) and `store.py` (`stamp_created`, `touch`, new `_clock_stamp`) — one-line why: PRD §2.4's "The system never reads the wall clock" requires all server-minted timestamps to derive from the logical clock.

**Final state:** 8/8 rounds, 97/97 passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-08-14T11:50:00.000Z

Step 8 complete. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1695_congregation_youth_program_mission_trip/workspace/PRD_FINALIZED.md`.

### Summary

**Line counts / delta:** PRD.md 383 lines, PRD_FINALIZED.md 383 lines — 0% delta (byte-identical copy). **Zero edits were committed.**

**Changes:** none. Each of the three `<step_7_diff>` items was evaluated against the patch criteria and none qualified:

- **Item 1 (logical-clock timestamps; impl fix in `util.py`/`store.py`)** — No PRD edit. Step 7's own analysis ruled this "PRD §2.4 covers verbatim" (STEP 1a) and "uniquely derivable" (STEP 1b): §2.4's "The system never reads the wall clock... it never falls back to wall-clock time" is absolute and unscoped, and it composes with §2.2 (`api_request_timestamp`: "server-generated ISO 8601 UTC timestamp with three fractional digits") and §2.5 (`created_at`/`updated_at`: "ISO 8601 UTC timestamp with three fractional digits") to leave the logical clock as the only possible source for every server-minted timestamp. The Step 7 fix brought the implementation into line with the PRD; it revealed neither PRD-silence nor PRD-mismatch. Per method steps 1–2 ("patch only when impl pinned a choice PRD left open"; "where PRD already determines behavior, keep prose verbatim"), prose was kept verbatim.
- **Item 2 (`test_13` raw `Response` stored in ctx)** — pure test-code bug, assertion unchanged, diff explicitly states "No PRD implication." No edit.
- **Item 3 (`test_14` expected literal 35000 → 25000)** — pure test arithmetic error, asserted rule preserved, diff explicitly states "No PRD implication." No edit.

**Pre-edit search log (candidate edit for item 1 — evaluated, not committed):**
- (a) Subject: clock source for all server-minted timestamps (envelope `api_request_timestamp`; entity `created_at`/`updated_at`; clock-stamped domain fields).
- (b) Paths enumerated and grepped/read: `implementation/util.py:34-83` (`_now_timestamp` feeding `success_object`/`success_list`/`error_response` — the only envelope builders); `implementation/store.py:32,45-78` (`clock_dt` default `2026-08-01T00:00:00Z`, `stamp_created`, `touch`, `_clock_stamp` — the only `created_at`/`updated_at` minters; all other files merely read/serialize those fields, confirmed by repo-wide grep over `domain.py`, `routes_core.py`, `routes_people.py`, `routes_money.py`, `routes_staff.py`); `implementation/routes_money.py:36,111` (`posted_at`/`received_at` via `DB.clock_string()`); `implementation/routes_core.py:382` (`debriefed_at`); `implementation/routes_staff.py:145-146` (`cleared_at`/`expires_at`); `implementation/routes_people.py:360` (`barred_until`); `implementation/domain.py:192` (`current_screening_expires_at`); repo-wide grep for `datetime.now|utcnow|time.time` confirming zero remaining wall-clock reads. Also checked the asserting test/helper (`test_suite/test_01...py:66-69`, `test_helpers/assertions.py:47-50`) — `assert_same_instant` compares instants semantically, so the pin is clock source, not string format; §2.5's three-fractional-digit format claim matches `_clock_stamp` exactly.
- (c) Outcome: every enumerated path is already fully and correctly described by existing §2.2/§2.4/§2.5 prose (including the per-field clock pins in §3.2/§3.4/§3.7/§3.8 for `debriefed_at`, `posted_at`, `received_at`, `cleared_at`, `barred_until`). No wording adjustment made — any added sentence would restate what the PRD already uniquely determines, violating the minimal-change rule, and risks a false-universal mismatch against the whole-seconds rendering `fmt_clock` produces for non-common timestamp fields.

## Step 9: Complete PRD — 2026-08-14T12:04:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1695_congregation_youth_program_mission_trip/workspace/PRD_COMPLETED.md`.

**Volume:** PRD_FINALIZED.md 383 lines / 67,109 chars → PRD_COMPLETED.md 383 lines / 70,157 chars (char-delta +3,048; all edits in-paragraph, no new sections, line count unchanged).

**Counts:** 21 ambiguity-pins, 6 mismatch-revisions (27 changes total).

**Mismatch revisions:**
- §2.1 — revise — mismatch — scholarship SOD scoped to approvals only ("a scholarship reviewer approving an application must differ…"; a denial carries no such check), matching impl which runs the guardian-uid comparison only on `decision == "APPROVE"` — implementation/routes_money.py:238-241
- §2.3 — revise — mismatch — list ordering pinned to creation order (impl sorts by creation sequence, diverging from `created_at` order when the clock is set backward) — implementation/web.py:91
- §3.1 — revise — mismatch — program close: non-`OPEN` program → `ERR_PROGRAM_NOT_OPEN`; open trips → `ERR_PROGRAM_HAS_OPEN_TRIPS` (PRD had the latter covering both) — implementation/routes_core.py:99-103
- §3.2 — revise — mismatch — logistics PATCH permitted in `DRAFT`/`REGISTRATION_OPEN`/`REGISTRATION_CLOSED`/`ROSTER_LOCKED` (PRD's enumeration omitted `ROSTER_LOCKED`, which impl permits) — implementation/routes_core.py:220-222
- §3.3 — revise — mismatch — registration-review APPROVE gate order corrected to impl order: SOD → `SUBMITTED` → trip `REGISTRATION_OPEN` → not-barred → forms `VERIFIED` (PRD had listed SOD third, forms before barred) — implementation/routes_people.py:234-260
- §3.5 — revise — mismatch — decide APPROVE gate order corrected to: SOD → `UNDER_REVIEW` → registration state → fund → zero-award — implementation/routes_money.py:238-262

**Ambiguity pins:**
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` (incl. negative offset) rejected with `ERR_INVALID_REQUEST` (400) — implementation/web.py:67-86
- §2.4 — insert — ambiguity — clock set accepts any valid instant, no monotonicity constraint — implementation/routes_core.py:25
- §2.4 — insert — ambiguity — clock-stamped domain timestamps render whole seconds when no sub-second component; only `created_at`/`updated_at`/`api_request_timestamp` always carry three fractional digits — implementation/util.py:130-135, implementation/store.py:70-75
- §2.5 — insert — ambiguity — `version` starts at 1 — implementation/store.py:50
- §2.5 — insert — ambiguity — per-request coalescing: one increment per entity per request; no-change recomputes don't bump; successful direct writes always bump — implementation/store.py:57-68, implementation/domain.py:97-105
- §2.8 step 6 — insert — ambiguity — within-tier state-gate order runs most-specific-resource-outward (form/application/lodging → registration → trip/account → program) — implementation/routes_people.py:213-217,428-432; implementation/routes_money.py:147-151,298-302; implementation/routes_staff.py:439-444
- §2.9 — insert — ambiguity — `seats_taken` counts `APPROVED`+`CONFIRMED`; `confirmed_youth_count` counts `CONFIRMED` — implementation/domain.py:108-113
- §3.1 — insert — ambiguity — scholarship-policy replacement not gated on program status; available after close — implementation/routes_core.py:76-91
- §3.2 — insert — ambiguity — `chaperone_ratio` above program default → `ERR_INVALID_REQUEST`, evaluated after program existence/OPEN at create and after version/capacity-floor at edit — implementation/routes_core.py:143-145,229-233
- §3.2 — insert — ambiguity — new trip's `ratio_compliant` reads true (zero required, zero cleared) — implementation/routes_core.py:169
- §3.2 — insert — ambiguity — early debrief → `ERR_TRIP_STATE_FORBIDS_ACTION`; all four debrief fields required, counts non-negative — implementation/routes_core.py:367-377
- §3.2 — insert — ambiguity — cancelling a `DEBRIEFED`/`CANCELLED` trip → `ERR_TRIP_STATE_FORBIDS_ACTION` — implementation/routes_core.py:402-403
- §3.3 — insert — ambiguity — registration create against a non-`REGISTRATION_OPEN` trip → `ERR_TRIP_STATE_FORBIDS_ACTION` — implementation/routes_people.py:114-115
- §3.3 — insert — ambiguity — waitlist-head double ties broken by creation order — implementation/routes_people.py:285
- §3.3 — insert — ambiguity — resubmit re-applies the `MEDICAL_RELEASE` non-empty-notes rule; prior `reviewed_by_user_id` retained — implementation/routes_people.py:462-468
- §3.5 — insert — ambiguity — DENY gated only by `UNDER_REVIEW` (no SOD or registration-state check) — implementation/routes_money.py:242-249
- §3.5 — insert — ambiguity — rescind records `reason` into `decision_reason`; no gates beyond `APPROVED` status — implementation/routes_money.py:314-330
- §3.6 — insert — ambiguity — final-cost-share ordering double ties broken by creation order — implementation/routes_core.py:323-326
- §3.8 — insert — ambiguity — background-check advance accepts an optional replacement `vendor_reference` — implementation/routes_staff.py:123,135-136
- §3.9 — insert — ambiguity — blank `vehicle_code` on a `TRAVEL` segment counts as missing (`ERR_INVALID_REQUEST`) — implementation/routes_staff.py:324-328
- §4 — insert — ambiguity — `GET /registrations/{id}/fundraising-account` returns a list envelope holding the single account (not an object envelope) — implementation/routes_money.py:72-80

Everything else in the impl (endpoint surface, role tables, error catalogue, fee/late-fee/need-score/award/share formulas, cascade shapes, sweep conditions, boundary semantics) was already uniquely pinned by PRD_FINALIZED.md and left untouched.
