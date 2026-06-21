# Worklog — task_0319_laundromat_self_service_laundry

## Step 1: Create task directory — 2026-06-13T03:49:27.000Z

Created `tasks/task_0319_laundromat_self_service_laundry/` and `tasks/task_0319_laundromat_self_service_laundry/workspace/`. Difficulty: Expert (passed to scaffold-generator in Step 2). Output directory fixed by caller; no auto-increment scan performed.

## Step 2: Generate scaffold (Expert) — 2026-06-13T04:13:06.000Z

All three scaffold artifacts are written and pass the linter cleanly. (The pre-existing `worklog.md` and empty `workspace/` directory were already present; I only created the three required YAML files.)

### Summary

Generated the Expert-tier scaffold for **task_0319 — Laundromat & Self-Service Laundry**. All three files (`SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) parse and `scaffold_lint.py` returns **VERDICT: clean lint**.

**Complexity profile:** primary archetype *pricing engine* + secondary *quota/allocation*; flat entity topology; parallel state-machine shape; peer-role model; immediate consistency. Layers: dual-variant calc, cascading side effects, rate/threshold triggers, derived-field reconciliation.

**Scaffold counts:**
- **Entities: 10** — PricingPlan, Machine, Member, Shift, VendTransaction, ReloadTransaction, WdfOrder, RefundClaim, LostFoundItem, LoyaltyLedgerEntry (append-only, `common_fields:false`).
- **State machines: 7** — PricingPlan (linear), Machine (cyclic IDLE→RUNNING→DONE→IDLE + FAULT/OUT_OF_SERVICE branches), VendTransaction (parallel payment_status × cycle_status), WdfOrder (branching), RefundClaim (branching approve/deny), Shift (linear reconcile), LostFoundItem (branching claim/dispose). Plus 2 concurrency rules (OCC on Machine.version for vend-create, on RefundClaim.version for refund-approve).
- **Calculations: 6** — vend_quote_cents (forward), vend_charged_cents (chronological), reload_bonus_cents (tiered), wdf_total_cents (minimum-before-rush rounding order), shift_expected_drawer_cents (aggregation), refund_requested_cents.
- **Validations: 18** (priority-ordered, 8 categories). **Errors: 18.** **Endpoints: 53** (includes test-driving `/_clock/advance` and bare filtered-list collections added for FK reverse-reachability). **Roles: 3** — Manager (opaque), Attendant (opaque), Member (entity_backed).

**Difficulty design (§1.8):** all 9 §0.5 rules × **2 instances = 18 instances**, each with empty-DB-reachable `setup_api_calls`, literal-locked asserts (all numeric values computed in Python: e.g. dryer-surge quote 338, WDF rush-on-minimum 1875, drawer variance −50, refund wallet conservation 5500, loyalty +3/−3 net 0), and falsifiable distinguishing aspects across distinct entity domains / error-category pairs / interval semantics / conserved quantities.

**Corner design (§1.9):** **40 active instances + 4 `excluded_because` stubs (44 total)** across 9 guide sections (entities 9, state_machines 6, calculations 5, validations 9, endpoints 2, rbac 4, cross-cutting 5, consistency 1, errors 3-stub).

**Key fixes during generation:** quoted `?`-suffixed flow-sequence tokens and block-styled bracketed `grounds:` (YAML parse); set `api_prefix: /` so the linter's flat-collection segment derivation works; added single+list collection GETs (`/vends`, `/reloads`, `/loyalty-ledger`) and a `current_vend_id?` filter for FK reverse-reachability; corrected three `expected_machine_version` captures to re-read the machine via GET (the vend response carries the VendTransaction version, not the machine's); reclassified Attendant as `opaque` (resolving operator-id identity for non-ownership ops while keeping member ownership entity_backed); removed the unreachable `VOIDED` reload enum (enum closure); and pinned the CASH-refund-to-drawer attachment to the referenced vend's shift_id for determinism.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T04:13:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0319_laundromat_self_service_laundry/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-13T04:18:43.000Z

**Output:** `workspace/PRD.md`

**Document metrics:** 257 lines, 5 top-level sections. §2: 10 subsections (cross-cutting principles). §3: 8 subsections (entity-lifecycle/business-process grouping). §4: 53-row endpoint table (Method, Path, Description, Authorized Role(s), incl. `/_clock/advance`). §5: 18-row error table.

**Hard Contract reports:** Contract 1 (field coverage) 83/83 present, 0 missing — PASS. Contract 3 (path purity, §3) 365 backtick tokens scanned, 0 path/method tokens — PASS. Contract 2 (rule coverage): 18 validations expressed via fixed priority order in §2.10; 2 OCC rules (vend-create→expected_machine_version, refund-approve→expected_claim_version, both ERR_STALE_VERSION/412); all state machines fully expressed; 6 calculations precise prose; all 18 error IDs appear ≥2×; sibling-branch symmetry preserved — PASS.

**Notable scattering/coverage decisions:** Two rounding conventions (half-up for surge multiplier + WDF rush; floor for loyalty points + reload bonus) consolidated in §2.6, re-stated inline at each formula. Dual-variant pricing (forward `quoted_amount_cents` vs chronological `charged_amount_cents`) in §3.3 with pinned free-credit→loyalty order. Vend params scattered: core capture (`payment_method`, `dry_blocks`, `expected_machine_version`) in §3.3, OPEN-shift `shift_id` stamping/drawer-aggregation in §3.6. Constants embedded with unit conversions (wdf_minimum 1500→"fifteen dollars", reload tiers, RUSH_BPS 2500→"twenty-five percent"). DISPOSAL_HOLD_HOURS left as named "disposal-hold window" (scaffold gives no numeric default). OCC framed purely in stale-version terms. Both SCAFFOLD design YAMLs were not opened, per the hard constraint.

## Step 5: Generate unit tests — 2026-06-13T05:06:52.000Z

Generated complete test infrastructure under the design-index-only contract.

**Stage 1 — `test_helpers/` (9 files):** `types.py` (TypedDicts + enums; `LoyaltyLedgerEntry` carries only `id`+`created_at`, append-only per PRD §2.4); `api_client.py` (one method per PRD §4 endpoint, all ~50 incl. `/_clock/advance`); `api_errors.py` (full §5 catalogue + HTTP-status map); `assertions.py`, `factories.py` (input fields only), `constants.py`, `test_users.py` (Member entity_backed via `make_member_headers`; Manager/Attendant opaque), and `fixtures.py` (composite setup helpers: funded member, APP_WALLET vend, submitted/refunded claim cascades, shift-with-coin-and-cash-reload drawer, redeem→free-credit chain, WDF ready/paid).

**Stage 2 — `test_suite/` (conftest + 7 test files, 76 test functions):**
- Queue A (Difficulty): 18/18 instances translated — every instance has exactly 2 tests (36 tests), 0 skipped.
- Queue B (Corner): 40/40 non-stub instances translated, ≥1 test each (40 tests); 4 `excluded_because` stubs (3 errors, 1 calculations) correctly NOT translated.

**Verification:** 76 tests, 76 `Design:` tags, 1:1 parity, all copied verbatim from source YAML. All PRD citation quotes confirmed verbatim (one trailing-punctuation mismatch found+fixed). No skip/skipif/xfail; no scaffold/§1.x leakage. All imports resolve; all files AST-parse cleanly. API client signatures cross-checked against installed framework source.

**PRD-coverage observations:** All design-index instances passed the PRD-first two-condition filter; no forced skips. Corner instances `missing_headers_returns_401`, `pagination_limit_out_of_range_returns_422`, `suspended_member_reload_returns_409` all explicitly PRD-covered (§2.1, §2.3, §3.4).

## Step 6: Generate implementation — 2026-06-13T05:06:52.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`. Impl-gen reports the full 76-test suite passes 76/76 under `prd-bench-local-run --isolation per-test-server` (to be independently confirmed by Step 7's 8-round sweep).

**Files (22 source + start.sh):** `start.sh` (guarded-install launcher, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000); `app.py` (entry, blueprint registration, error handlers, `socket.getfqdn` fast-path to avoid macOS reverse-DNS stall on `0.0.0.0`, `Connection: close` on every response); `db.py` (in-memory dicts + logical capture clock), `errors.py`, `response.py`, `middleware.py` (auth/RBAC); `routes/` (pricing_plans, machines, members, transactions, shifts, wdf_orders, refund_claims, lost_found, clock); `services/` (calc, common, cycle, shift_calc, serialize).

**Storage:** in-memory only — process-local dicts keyed by id, no persistence, no seeding at startup; fresh boot wipes all state.

**Endpoints: 53** (all PRD §4, incl. `/_clock/advance`).

**State machines:** Machine cyclic IDLE→RUNNING→DONE→IDLE + FAULT/OUT_OF_SERVICE; VendTransaction parallel (payment_status × cycle_status); WdfOrder branching; RefundClaim approve/deny; Shift reconcile; PricingPlan activation cascade; LostFoundItem claim/dispose.

**Calculations:** dual-variant vend pricing (forward `quoted_amount_cents` surge round-half-up vs chronological `charged_amount_cents` pinned free-credit→loyalty floor order); tiered reload bonus (highest-tier, floored); WDF total (minimum-floor-before-rush, half-up rush); shift drawer aggregation/variance; refund-requested derivation. All money integer cents via `Decimal` ROUND_HALF_UP/floor.

**Validation/RBAC/OCC:** priority-ordered (auth→existence→well-formedness→ownership→state→OCC→business rules) with exact error IDs; OCC on `expected_machine_version` (vend) and `expected_claim_version` (refund approve); full refund cascade (wallet credit, loyalty reversal ledger, lifetime-spend reduction, CASH-destination shift drawer).

**Notable fidelity decision (flag for Step 8/9):** Filing a refund claim against an already-REFUNDED vend is *allowed*; rejection enforced only at approve time — matches §1.8 test recipe / test_03 / test_07, which override PRD prose that reads as if filing should also be blocked.

**start.sh boot:** harness runs `bash start.sh` from `./implementation/`; `start.sh` does `cd "$(dirname "$0")"` (cwd-independent), installs deps only if Flask missing, `exec`s server foreground. Boots + responds in ~0.25s.

## Step 7: Test-iterate-fix loop — 2026-06-13T05:10:01.000Z

Clean exit. All 8 parallel rounds passed 76/76.

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Result:** All 8 concurrent rounds passed **76/76** tests — `passed=76, total=76, failed=0, errors=0, skipped=0` in every round (independently confirmed by orchestrator reading all 8 `results.{1..8}.json`). The union of failing tests across all 8 rounds is empty, so there is no flakiness signal and no diagnostic protocol triggered.

**Tests deleted:** None. No test exhibited PRD-silence or non-unique-derivability because no test failed.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `implementation/`:** None needed.

**Notes:**
- One transient false alarm came from the subagent's own initial parse script keying on `outcome` instead of the actual `status` field in `results.*.json`; the corrected read (and a status-tally cross-check) confirms every test's status is `passed` in all 8 rounds.
- The implementation already satisfies the in-memory-only constraint (process-local dicts in `db.py`, no seeding at startup); `start.sh` re-invocation wipes state, consistent with per-test-server isolation.
- Each round took ~47.5s wall time; the 8 ran concurrently, so total sweep wall time stayed at roughly that figure.

## Step 8: Finalize PRD — SKIPPED — 2026-06-13T05:10:01.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the Step 7 fix sites, so no `PRD_FINALIZED.md` is produced. Step 9 will start from PRD.md.

## Step 9: Complete PRD — full impl scan — 2026-06-13T05:14:57.000Z

Produced `workspace/PRD_COMPLETED.md` (started from PRD.md, since Step 8 was skipped / no PRD_FINALIZED.md).

**File comparison (PRD.md → PRD_COMPLETED.md):** line count 257 → 257 (unchanged; all edits in-paragraph). Char count 40,179 → 41,008 (delta +829).

**Counts:** 4 ambiguity-pins, 1 mismatch-revision.

**Changes (one per edit):**
- §3.3 (Capturing a Vend) — insert — ambiguity — PRD said only "the acting member's wallet" for `APP_WALLET`; pinned that a `member_id` is required and an `APP_WALLET` capture with none → `ERR_INVALID_REQUEST` (422) — `routes/machines.py:235-236`
- §3.4 (Member Wallet, redemption) — insert — ambiguity — PRD pinned only the points-threshold check for redeem; pinned that redemption also requires an `ACTIVE` plan (`ERR_NO_ACTIVE_PLAN`) and an `ACTIVE` member (`ERR_MEMBER_NOT_ACTIVE`), in impl's check order — `routes/members.py:221-224`
- §3.5 (WDF pay) — insert — ambiguity — PRD said "the order must name a member" for `APP_WALLET` pay but gave no error; pinned a walk-in order with no member → `ERR_INVALID_STATE` (409) — `routes/wdf_orders.py:149-150`
- §3.7 (Refund Claim filing) — revise — mismatch — PRD read as if a claim "may not be filed against a vend whose `payment_status` is already `REFUNDED`; rejected with `ERR_ALREADY_REFUNDED`." Impl performs no payment-status check at filing (claim created `SUBMITTED`); guard fires only at approval. Revised to state filing succeeds and `ERR_ALREADY_REFUNDED` is enforced at adjudication — `routes/refund_claims.py:48-70` (no filing-time guard), `routes/refund_claims.py:120-121` (approve-time guard)
- §3.8 (Lost & Found disposal) — insert — ambiguity — PRD referenced "the disposal-hold window" without a value; pinned it at 24 hours — `routes/lost_found.py:28,114`

**Behaviors checked and left unchanged (already pinned):** envelope shapes, §2.10 validation-order priorities, reload requiring an active plan (§3.1), `_clock/advance` empty-data 200, loyalty REVERSAL `points_delta` = full `-loyalty_points_earned` with floored balance (§3.7), shift-drawer aggregate formulas, surge/floor/rush rounding conventions.

---

## Pipeline complete

Final task directory `tasks/task_0319_laundromat_self_service_laundry/` contains: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (conftest + 7 test files, 76 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, implementation/}. PRD_FINALIZED.md correctly absent (Step 8 skipped). Final verification: 8/8 stability-sweep rounds passed 76/76.
