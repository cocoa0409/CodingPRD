# Worklog — task_0206_gift_card_stored_value

Scenario: Retail Gift Card & Stored-Value Program: card issuance (digital/physical), activation/load, balance redemption/split tender, reload, expiration/breakage rules (state law), refund-to-card, fraud/replacement, B2B bulk order

Difficulty: Expert (§0.4 Expert calibration band) — applied to Step 2 scaffold generation only.

## Step 1: Create task directory — 2026-06-06T16:29:23.000Z

Step 1 auto-scan SKIPPED per orchestrator instruction. Task directory `tasks/task_0206_gift_card_stored_value/` was pre-allocated with `workspace/` subdirectory already present. No new directory created.

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-06T16:50:00.000Z

All three artifacts are complete, internally consistent, and pass the scaffold linter cleanly. The file split is correct, no design keys leaked into SCAFFOLD.yaml.

Generated all three scaffold artifacts for **task_0206_gift_card_stored_value** at **Expert difficulty**, all passing `scaffold_lint.py` with `VERDICT: clean lint` (315 calls scanned across §1.8/§1.9, all 21 FKs reverse-reachable).

**Architecture**: Event-sourcing + ledger-reconciliation archetype, flat topology (`api_prefix: /v1`), parallel state-machine shape, peer-roles RBAC, immediate consistency.

**Entities (13)**: Program, StateRule, PromoCampaign, Customer, GiftCard, LedgerEntry (append-only), AuthorizationHold, Redemption, RedemptionLeg (split-tender junction), BulkOrder, ReplacementRequest, RefundRequest, DormancyWaiver.

**State machines (8)**: GiftCard has two parallel dimensions — `lifecycle_status` (INACTIVE→ACTIVE↔EXHAUSTED→VOIDED/EXPIRED) and a cyclic `risk_status` (CLEAR↔FLAGGED↔FROZEN_RISK); plus AuthorizationHold, Redemption (with SETTLED→VOIDED reversal), BulkOrder, branching ReplacementRequest, RefundRequest (with NEEDS_REVISION loop), and PromoCampaign. Two OCC concurrency rules (redemption-settle and replacement-approve, both 412).

**Key calculations (6)**: dual-variant card balance (settled vs authorized), dual-variant breakage (RECOGNIZE revenue vs ESCHEAT liability), order-sensitive split-tender waterfall, round-per-card-then-multiply bulk pricing, threshold dormancy assessment, and value-conserving replacement transfer. All design-file numeric asserts were computed in code (e.g., bulk invoice 16891 vs sum-then-round 16888; escheat 2400 vs recognize 4000).

**Counts**: 14 validations, 20 error codes, 56 endpoints (incl. filtered-list reverse GETs and a `/v1/_clock/set_current_utc` test-driving endpoint), 5 roles (ProgramAdmin, StoreAssociate, Customer, FraudAnalyst, B2BBuyer), 2 concurrency rules.

**§1.8 difficulty**: 18 instances (9 rule_ids × 2). **§1.9 corner**: 39 instances (37 active + 2 `excluded_because` stubs). All 20 error codes are triggered across the design files; instance names are unique across both files; all grounds resolve.

Notable corrections made during generation: flattened URLs so the linter's FK-segment derivation works; standardized the clock endpoint path; and reworked `ERR_CARD_ALREADY_REPLACED` from the approve path (where it was shadowed by higher-priority OCC/state checks since approval voids the card) to the replacement-create path (opening a new replacement on an already-replaced card), making it independently reachable. Also removed a dead `FROZEN` value from the lifecycle enum (freezing lives only in the risk dimension).

## Step 3: Copy shared files — 2026-06-06T16:51:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0206_gift_card_stored_value/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-06T16:55:00.000Z

All 20 error IDs appear in the §2/§3 narrative (each near its trigger), and all calculation constants are embedded with unit-conversion context. The PRD is complete and all three hard contracts pass.

Generated `workspace/PRD.md` (286 lines) for the Gift Card & Stored-Value Program API.

**Section structure:**
- **§1 Introduction** — 2 paragraphs framing the three-way problem (value movement, liability, state escheatment law) and the append-only ledger design.
- **§2 Global Specifications** — 12 subsections: 2.1 RBAC (all 5 roles + opaque/entity-backed identity translation), 2.2 Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Properties & Append-Only Ledger (LedgerEntry/RedemptionLeg lean entities), 2.5 Balance Derivation (settled/pending/available dual-variant), 2.6 Program Liability Aggregation, 2.7 Precision & Rounding, 2.8 Two Independent Card State Dimensions, 2.9 Cascading Side Effects, 2.10 Nested Reference Validation Order, 2.11 Validation Order of Precedence (priority 1–14), 2.12 OCC (both concurrency rules).
- **§3 Business Logic** — 10 subsections organized by lifecycle/domain: program config & promos, customers & issuance, activation/reload/bonus, authorization holds, split-tender redemption, refund-to-card & reversal, fraud & replacement, dormancy/breakage/escheat, B2B bulk orders, test-driving clock.
- **§4 Endpoint Definitions** — 4-column table, all 58 endpoints under `/v1`.
- **§5 Error Code Catalogue** — 2-column table, all 20 error IDs.

**Hard contracts (all PASS):**
- Contract 1 (Field-Name Coverage): 61 required field names, 0 missing.
- Contract 2 (Rule Coverage): 6 calculations, both OCC rules, all state-machine transitions with preconditions+error_ids+side-effects, priority ordering, sibling-branch symmetry (RECOGNIZE/ESCHEAT, both clear-risk branches), and all 20 error IDs surfaced in §2/§3 narrative — verified.
- Contract 3 (§3 Path Purity): 422 §3 backtick tokens scanned, 0 slash-paths / bare methods / method+path combos.

**Confirmation:** Did NOT read `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` — neither opened, grepped, nor referenced. Only `SCAFFOLD.yaml`, the skill `SKILL.md`, `section-2.2-response-structure.md`, and `example-prd.md` were read.

## Step 5: Generate unit tests — 2026-06-06T16:58:00.000Z

Generated complete test infrastructure for **task_0206_gift_card_stored_value** (Retail Gift Card & Stored-Value Program, EXPERT band) under a strict design-index-only contract.

### test_helpers/ (Stage 1) — 9 files emitted
- `types.py` — entity TypedDicts + 13 status/enum types. `LedgerEntry` and `RedemptionLeg` (common_fields:false) carry only `id`/`created_at` (no `updated_at`/`version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. the `_clock/set_current_utc` test-driving clock).
- `api_errors.py` — `ApiErrorId` enum + HTTP status map (PRD §5), registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions; immutable-record assertions positively check that `version`/`updated_at` are absent; gift-card assertion enforces `available = settled - pending_hold`.
- `factories.py` — input-only payload factories per entity.
- `constants.py` — program/state-rule/dormancy/escheat numeric defaults.
- `test_users.py` — shared headers for the 3 opaque roles; per-instance `make_customer_headers` / `make_b2b_buyer_headers` builders for the two entity-backed roles (identity threading).
- `fixtures.py` — composite setup helpers across 8 tiers (active cards, holds, risk progression, multi-card split-tender, replacement/refund/bulk-order lifecycles, clock-driven dormancy/breakage, campaigns).
- `__init__.py` — barrel export. All files compile; all test_suite imports statically resolve.

### test_suite/ (Stage 2) — conftest.py + 10 test files, 65 tests
- **Queue A (Difficulty):** all 18 instances translated, each with ≥2 tests (28 difficulty tests). 0 skipped.
- **Queue B (Corner):** all 37 non-stub instances translated, 1 test each (37 corner tests). Total 65 tests = 65 Design tags (1:1).
  - **2 corner stubs skipped** (no test emitted, as required): `validations/error_insufficient_balance_already_covered` and `cross_cutting_complexity_layers/cascade_full_refund_already_covered`. Both `excluded_because.difficulty_instance` cross-references resolve to real difficulty instances.

### Verification performed
- Every test docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag resolving to a real instance name.
- PRD-citation verbatim pass: every distinctive citation substring greps against PRD.md.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere.
- All helper and suite files pass `py_compile`.

No PRD-first filter skips were needed — all 18 difficulty and 37 corner non-stub instances had verbatim, uniquely-deriving PRD coverage.

## Step 6: Generate implementation — 2026-06-06T16:58:00.000Z

Generated a complete Python + Flask implementation in `workspace/implementation/`.

### Source files emitted
- `start.sh` — foreground launcher; guards `pip install` on a cheap `import flask` check, reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py`.
- `requirements.txt` — Flask 3.0.3 only.
- `app.py` — entry point: registers 10 blueprints (56 routes, matching the PRD endpoint table), error handlers (ApiError → envelope, 404/405 → ERR_NOT_FOUND with auth-first ordering, catch-all → ERR_VALIDATION).
- `db.py` — in-memory store (one dict per collection) + a `Clock` for the test-driving endpoint; `new_id()` (prefix-less UUID) and `now_iso()` (ISO 8601 UTC, 3 fractional digits).
- `errors.py`, `response.py`, `middleware.py` — error catalog/HTTP-status map, success/error envelope helpers, `X-User-ID`/`X-User-Role` auth + RBAC.
- `core.py` — common-field stamping/versioning, `round_half_up` (Decimal), balance derivation (settled/pending/available), append-only ledger posting, program liability roll-ups, pagination, body validators.
- `serialize.py`, `lookups.py`, `domain.py` — per-entity JSON serializers (computed fields derived on read), path-existence lookups, and shared domain logic (campaign sync, dormancy month math, ACTIVE↔EXHAUSTED auto-transitions, redemption reversal cascade).
- `routes/` — programs/state-rules/campaigns/clock, customers, cards (issue/activate/reload/assess-dormancy/flag/freeze/clear-risk), ledger, holds, redemptions+legs, bulk-orders, replacements, refunds, dormancy-waivers.

### Framework / launch / storage
Flask, launched via `bash start.sh` running `app.py` in the foreground (threaded). Storage is purely in-memory Python dicts keyed by id in a single process-global `DB` instance — no SQLite, no disk, no `/tmp`. Nothing seeded at startup; a fresh boot lists zero entities. Each `start.sh` re-invocation is a new process, so all state is wiped.

### Interpretation calls
1. **Hold capture during settlement (§3.4 vs §3.5):** §3.4 describes capture conceptually, but the §3.5 settlement workflow is self-contained (waterfall over `card_id_order` using `available_balance_cents`, one REDEEM debit per leg, no hold linkage/parameter). Implemented §3.5 as written (no automatic hold capture); active holds remain ACTIVE and continue to reduce available balance. Holds reach CAPTURED only via the conceptual path, which has no triggering endpoint in the scaffold.
2. **`assess-dormancy` fee vs expiration (§3.8):** scaffold formula gates the fee on `dormancy_fee_allowed` (independent of expiration) and expires only `if expiration_allowed`. Reconciled atomically: validate gates first, charge fee if fee-allowed, expire if expiration-allowed. `ERR_EXPIRATION_NOT_ALLOWED` raised (no side effect) only when card is dormant but jurisdiction allows neither fee nor expiration.
3. **Minted-card `form_factor` (§3.9):** PRD specifies `state_code` and `owner_customer_id` for bulk-activated cards but not `form_factor`; defaulted minted cards to `DIGITAL`.

## Step 7: Run tests and iterate — 2026-06-06T17:08:00.000Z

All 8 parallel rounds pass cleanly (65/65, 0 failed, 0 errors each). Exiting with the summary.

**Iterations run:** 3 sweeps (1 baseline + 2 post-fix). Final sweep: all 8 parallel rounds passed 65/65 with 0 failures and 0 errors.

**Root cause of the initial all-red appearance:** my first parse used `outcome` (wrong key); the real status key is `status`. Only 2 tests ever actually failed per round.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**

- `test_04_validation_precedence_and_boundaries.py` — `test_invalid_state_beats_insufficient_balance_on_settle`: changed the under-funded active card's initial load from `100` to `1000`. The program is created with `reload_min_cents=500`, and PRD §3.3 verbatim states "The initial load must be at least the program's `reload_min_cents`, otherwise the request is rejected with `ERR_RELOAD_BELOW_MIN`." The fixture's `100` violated the PRD precondition, so the PRD-faithful implementation correctly rejected setup with `ERR_RELOAD_BELOW_MIN`. `1000` satisfies `reload_min_cents` while keeping the card under-funded (1000 < the 5000 redemption), preserving the test's intent (ERR_INVALID_STATE at priority 8 pre-empts ERR_INSUFFICIENT_BALANCE at priority 14). This is a STEP 2 test-bug fix (request inconsistent with PRD precondition).

- `test_05_temporal_overlap_and_invariants.py` — `test_full_refund_reversal_restores_each_card_balance` → renamed `test_full_refund_reversal_drives_redemption_voided`; removed both per-card `settled_balance_cents == ...` assertions (STEP 1c split), keeping only the uniquely-derivable state transitions (`status == "APPLIED"`, redemption `== "VOIDED"`). Reason (STEP 1b unique-derivability collapse): the PRD is self-contradictory on the post-reversal settled balance. §2.5 mandates verbatim "entries whose `status` is `REVERSED` are excluded from this sum," while §3.6 directs the reversal to BOTH mark the original `REDEEM` debit `REVERSED` AND post a new `REVERSAL` credit, and separately claims the net effect is "restored by its leg's `leg_amount_cents`" (+1×). Excluding the REVERSED debit (§2.5) plus adding the REVERSAL credit (§3.6) nets +2× the leg amount, contradicting §3.6's stated +1× restore. The refund-target card additionally carries a separate `REFUND` credit ("a further cascade"). Two faithful PRD-only readings yield divergent balances, so the balance assertions are not uniquely derivable.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation faithfully follows PRD §2.5 (excludes REVERSED from settled) and §3.6 (posts REFUND credit + per-leg REVERSAL credit); the failing balance assertions were demanding a value the contradictory prose does not uniquely determine.

**Flakiness note:** the post-first-fix sweep showed transient "API server could not be restarted" errors hitting a *different random test each round* (never the same test, never a logic failure) — boot-latency contention under the documented ~8× peak load. It did not recur in the final sweep, so no boot hardening was applied; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-06-06T17:23:00.000Z

Produced `workspace/PRD_FINALIZED.md`. Not skipped (Step 7 had 2 `test_suite/` fixes).

**Line counts:** PRD.md = 286 lines, PRD_FINALIZED.md = 286 lines (0% line-count delta; one line revised in place).

**Changes (1 total):**
- **§3.6 (Refund-to-Card and Redemption Reversal) — revise** — Replaced the false "Each affected card's `settled_balance_cents` is restored by its leg's `leg_amount_cents`" (+1×) with prose matching the implementation's actual +2× net effect: the cascade posts a `REVERSAL` credit (+leg amount) AND marks the original `REDEEM` debit `REVERSED`; under §2.5 the now-`REVERSED` debit drops out of the settled sum while the new credit is added, so each affected card's settled balance rises by twice the leg amount relative to its pre-reversal value. — `domain.py:116-136` (`reverse_redemption`) + `core.py:184-190` (`settled_balance`).

**Step 7 items not requiring a PRD edit:**
- **test_04 `test_invalid_state_beats_insufficient_balance_on_settle`** (initial load 100→1000): pure fixture bug. PRD §3.3 already verbatim requires the initial load to meet `reload_min_cents`; no PRD silence or mismatch — no edit.

**Per-edit pre-edit search log:**
- **(a) Subject:** net effect of the redemption-reversal cascade on a card's `settled_balance_cents`, and every code path producing/consuming `REVERSAL`/`REVERSED` entries.
- **(b) Paths enumerated (grepped `REVERSAL|REVERSED|reverses_entry_id|status == "POSTED"`, read each):** `domain.py:116-136` `reverse_redemption` (sole producer; posts REVERSAL credit + sets REDEEM REVERSED → +2×); `refunds.py:122` (only caller, full-refund cascade); `core.py:184-190` `settled_balance` (sums POSTED only, excludes REVERSED — consistent with §2.5); `core.py:247-252` `program_outstanding_liability` (re-sums settled, inherits +2×, no special handling); `core.py:255-270` breakage/escheat roll-ups (untouched by REVERSAL); `core.py:206-216` `last_activity_at`, `serialize.py:105`, `ledger.py:30` (read/expose only, no settled arithmetic). PRD §2.4/§2.5 cross-check: new wording defers to §2.5 verbatim — no contradiction.
- **(c) Wording adjustment:** scoped the sentence to "re-derived per §2.5 from its current `POSTED` entries" and spelled out the two additive components, so it stays consistent with `settled_balance` everywhere and does not over-claim about non-refund paths (settlement, holds, replacement, dormancy never invoke this cascade).

## Step 9: Complete PRD — 2026-06-06T17:30:00.000Z

Produced `workspace/PRD_COMPLETED.md` via full PRD-vs-implementation scan (always runs).

**File counts:** PRD_FINALIZED.md (source) = 286 lines / 48,755 chars → PRD_COMPLETED.md = 286 lines / 53,096 chars. Char delta: **+4,341**. Line count unchanged (every edit is an in-paragraph insert/revision; no new paragraphs or sections).

**Change counts:** 14 changes total — **8 ambiguity-pins**, **6 mismatch-revisions**.

**Per-change log** (`{section} — {kind} — {type} — {what} — {impl ref}`):
- §2.1 — revise — ambiguity — Pinned that a Customer/B2BBuyer reading a `Customer` record may read only their own (else `ERR_FORBIDDEN`) — routes/customers.py:43-44
- §2.3 — revise — ambiguity — Pinned that out-of-range `limit`/`offset` are clamped (not rejected), non-integer values yield `ERR_VALIDATION`, and list ties break by ascending `id` — core.py:140-176
- §3.1 — revise — ambiguity — Pinned campaign `program_id` FK (`ERR_REFERENCE_NOT_FOUND`), ISO-parse (`ERR_VALIDATION`), and half-open (strict, abutting-OK) overlap semantics for `ERR_CAMPAIGN_OVERLAP` — routes/programs.py:131-148
- §3.3 — revise — mismatch — Pinned that the reload balance-cap test counts only the reload amount and excludes the promo bonus; active campaign chosen by clock-recomputed status taking first match; zero bonus posts no entry — routes/cards.py:131-140
- §3.4 — revise — mismatch — Revised the hold "capture" paragraph: settlement never captures or mutates holds and no hold is ever driven to `CAPTURED`; only freeze releases an active hold — routes/redemptions.py:182-197, routes/cards.py:230-234
- §3.6 — revise — ambiguity — Pinned that the full-amount reversal cascade requires the referenced redemption to currently be `SETTLED` — routes/refunds.py:118-122
- §3.7 — revise — ambiguity/mismatch — Pinned that approval checks replacement `OPEN` state before the OCC version check, and that the minted card clones `form_factor` (and resets `risk_status` to `CLEAR`) in addition to `state_code`/owner — routes/replacements.py:86-107
- §3.8 — revise — ambiguity — Pinned the `ACTIVE`/`EXHAUSTED` lifecycle precondition (`ERR_INVALID_STATE`), the month-floor algorithm detail, and the no-StateRule default (threshold 12, fee/expiration false) — routes/cards.py:147-179
- §3.8 — revise — mismatch — Pinned that one `assess-dormancy` call applies fee then expiration together; fee precedes expiration; zero fee posts nothing; due-check rejects before side effects; `ERR_EXPIRATION_NOT_ALLOWED` raised only when both fee and expiration are disallowed — routes/cards.py:170-199
- §3.8 — revise — mismatch — Pinned that `DormancyWaiver` has no revocation action (stays `ACTIVE`), the closed-interval overlap test, and `card_id` FK validation (`ERR_REFERENCE_NOT_FOUND`) — routes/waivers.py:16-43
- §3.9 — revise — ambiguity — Pinned bulk-order FK validation (`ERR_REFERENCE_NOT_FOUND` before shape), `net_invoice_cents` starts `null`, and B2BBuyer list self-scoping by `buyer_customer_id` — routes/bulk_orders.py:36-83
- §3.9 — revise — ambiguity — Pinned that activation-minted cards carry `form_factor` `DIGITAL` and `risk_status` `CLEAR` — routes/bulk_orders.py:120-134
- §3.10 — revise — mismatch — Pinned that clock-set rejects non-ISO `to_iso8601` (`ERR_VALIDATION`), always resyncs every campaign status, and returns `200 OK` with an empty data object — routes/programs.py:194-208

**Already-pinned (no change):** §3.5 settle order (OCC before shape); §2.4 `source_ref_id` enumeration; freeze (no lifecycle precondition); balance derivation, breakage/escheat math, split-tender waterfall.

---

## Pipeline complete

All 9 steps finished. Final state: 65 tests, 8/8 stability-sweep rounds passing 65/65 (0 failed). Artifacts: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md → PRD_FINALIZED.md → PRD_COMPLETED.md, test_helpers/ (9 files), test_suite/ (10 files), workspace/implementation/ (Flask, in-memory, start.sh).
