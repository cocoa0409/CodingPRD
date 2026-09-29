# Worklog — task_2574_instant_payments_participation_liquidity_management

## Step 1: Create task directory — 2026-09-03T15:11:18.176Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2574_instant_payments_participation_liquidity_management` and its `workspace/` subdirectory. Index 2574 was pre-assigned by the invoking command; no scan of `./tasks/` was performed and no index was auto-allocated (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T16:56:00.000Z

All three scaffold artifacts are complete and lint-clean.

**Verdict block (verbatim from `scaffold_lint.py`):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    54
  §1.1 entities declared:     13
  §1.8 instances scanned:     22
  §1.9 instances scanned:     70
  Calls scanned (§1.8+§1.9):  1138

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files (all parse under `yaml.safe_load`):**
- `SCAFFOLD.yaml` — 3126 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2422 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4840 lines

**SCAFFOLD.yaml (§1.0–§1.7 only; confirmed it contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`):** 13 entities, 10 state machines, 2 concurrency rules, 11 calculations, 66 validations, 54 endpoints, 60 errors, 6 roles. Profile: primary `ledger_reconciliation` / secondary `quota_allocation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, flat topology, parallel state-machine shape, `segregation_of_duties`, `immediate` consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml — 9 rule blocks / 22 instances:** dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml — 8 sections / 90 instances (70 with full `test_recipe`, 20 `excluded_because` stubs):** entities 18, state_machines 13, calculations 15, validations 27, endpoints 6, rbac 5, cross_cutting_complexity_layers 5, consistency_model 1.

**Verification performed on parsed YAML (not grep):**
- All 112 instance names across both design files are unique.
- All 60 declared error ids appear in at least one instance's `assert` list (not merely in `grounds`), so every error is triggerable.
- All 20 `excluded_because` stubs cite a `difficulty_instance` name that actually exists in SCAFFOLD_DIFFICULTY_DESIGN.yaml, and none of them carries a `test_recipe`.

Scaffold-design notes worth knowing downstream: seven §1.0–§1.7 clarifications were made during authoring to close gaps the corner instances exposed — `ReturnRequest.returned_amount_cents` defaulting, RFP `response_deadline_at = min(expiry_at, delivered_at + RFP_RESPONSE_SLA_MINUTES)` on both entries into `DELIVERED` plus validation 84 / `ERR_RFP_EXPIRED` covering it, validation 85's `>=` late-honour comparison, validation 91 making the exception dimension one-shot (`ERR_DUPLICATE_RETURN_REQUEST` also fires once `exception_status` is terminal), and validation 68 extending fraud-review segregation of duties to the assignment endpoint as well as the decision.

## Step 3: Copy shared files — 2026-09-03T16:59:40.534Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:17:00.000Z

PRD generation for task 2574 is complete.

**Output:** `workspace/PRD.md`
**Size:** 447 lines / 103,425 bytes. Last heading: `## 5. Error Codes`; the file ends on the final error-table row (`| ERR_INSUFFICIENT_LIQUIDITY | 422 |`) — a real section boundary, no truncation, no audit footer.

**Top-level sections written**
- `# Instant Payments Participation & Liquidity Management API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Roles/RBAC, 2.2 Response Structure (byte-verbatim from `section-2.2-response-structure.md`, diff-verified), 2.3 Pagination, 2.4 Identity/Timestamps/Versions, 2.5 Logical Rail Clock & Business Dates, 2.6 Stale-View Protection, 2.7 Cents & Rounding, 2.8 Prefunded Position Ledger Identity, 2.9 Liquidity Bands / Posture Derivation / Queue Release, 2.10 Path Resolution & Reference Checking, 2.11 The Order in Which a Request Is Rejected (12-rung ladder)
- `## 3. Business Logic & Workflows` — 3.1 Onboarding, 3.2 Segment Policies & Customer Accounts, 3.3 Prefunded Position & Alert Remediation, 3.4 Origination (fraud score ORIGINATION), 3.5 Fraud Hold-and-Review (REVIEW_FINAL), 3.6 Clearing→Settlement & Irrevocability, 3.7 Requests for Payment, 3.8 Return Requests & Compensating Credits, 3.9 Outage Contingency / Throttled Queue / Diversion, 3.10 Business Day: Cutoff, Access Fees, Reconciliation, Closure & Sweep
- `## 4. API Endpoint Specifications` — 4-column table, exactly 54 rows (verified by count)
- `## 5. Error Codes` — 2-column table, exactly 60 rows (verified by count)

**Coverage verification (scripted against SCAFFOLD.yaml)**
- Contract 1 (field-name coverage): PASS — all 128 entity field names plus every endpoint `input`/path/query identifier appear verbatim in backticks; 0 missing.
- Contract 2 (rule coverage): PASS — all 60 error IDs appear in §1–§3 prose, not merely in the §5 table; all 45 distinct states across the 61 transitions of the 10 state machines are named in backticks; all 11 calculations are given as explicit formulas with pinned rounding/ordering (fraud score constants, per-transfer half-up fee then sum, floor rebate, waterfall ranking, 24h projection, both reconciliation variants); the 66 validations are covered by the §2.11 ordered ladder plus their scattered trigger conditions in §3.
- Contract 3 (§3 path purity): PASS — 862 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos; paths appear only in §4.
- No scaffold-internal leakage: zero hits for `calculations.`, `state_machines`, `section 1.x`, or any constant symbol (`*_MINUTES`, `*_CENTS`, `MAX_AMENDMENT_ROUNDS`, `QUEUE_TTL_*`) — all constants are stated numerically. No fuzzy quantifiers, no pseudocode.
- Hard constraint honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

**Scaffold contradictions resolved (worth relaying to the implementer/reviewer)**
1. Automatic fraud block (score >= 85 at origination): endpoint `side_effects` claim the customer account is restricted; the state machine says no review is created and the customer stays `ACTIVE`. PRD follows the state machine, stated emphatically.
2. RFP amendment: state machine overwrites `expiry_at` from the payload, endpoint input is `[amount_cents, memo?]` with "expiry is never extended". PRD follows the endpoint.
3. Threshold ordering: entity constraints say strictly-less-than, validation 47 allows equal adjacent values. PRD follows validation 47 (owner of `ERR_INVALID_THRESHOLD_ORDERING`).
4. Outage `ended_at`: PRD requires strictly after `started_at` and not later than the clock, both -> `ERR_INVALID_INTERVAL`.
5. `diverted_transfer_count`: defined as the number of transfers this declaration moved `INITIATED -> QUEUED_THROTTLED`; already-parked transfers are not recounted.
6. `ERR_ATTESTATION_INCOMPLETE` appears only in a scaffold note and is not one of the 60 catalogued errors — mentioned in §3.1 prose but deliberately absent from §5, with no invented HTTP status.
7. Cutoff's "no `ACCEPTED` transfer remains for the business date" precondition has no dedicated error in the scaffold; PRD attaches `ERR_INVALID_STATE_TRANSITION` (the only code whose `applies_to` covers cutoff).

§3 uses 10 subsections rather than the skill's suggested 5-9, because the domain has ten genuine workflow clusters; no Hard Contract restricts the count.

**Orchestrator truncation check (independent):** `wc -l` = 447; `grep '^## '` returns the 5 expected top-level sections; `tail -15` ends on a complete `| ERR_INSUFFICIENT_LIQUIDITY | 422 |` table row. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T18:53:00.000Z

Generation and verification are complete.

## Output locations (verified)

Both directories are at the **task root**. A `find` under `workspace/` for `test_helpers`/`test_suite` returns 0 hits — `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation`.

## Files written

`test_helpers/` — 2,360 lines total
`__init__.py` 40, `api_client.py` 223, `api_errors.py` 154, `assertions.py` 507, `constants.py` 122, `factories.py` 286, `fixtures.py` 865, `test_users.py` 96, `types.py` 67

`test_suite/` — `conftest.py` 60; queue A (Difficulty): `test_01` 222/4, `test_02` 187/4, `test_03` 235/6, `test_04` 352/6, `test_05` 172/4, `test_06` 334/7, `test_07` 245/6, `test_08` 275/6, `test_09` 223/4; queue B (Corner): `test_10` 500/18, `test_11` 339/6, `test_12` 373/5, `test_13` 670/13, `test_14` 771/13, `test_15` 442/5, `test_16` 344/5, `test_17` 262/3, `test_18` 108/1 (lines/tests).

Every .py in both directories passes `python3 -m py_compile`; `pyflakes` is clean on all test files (the only messages are the intentional re-export lines in `test_helpers/__init__.py`). No generated file contains the word "scaffold". `__pycache__` from the compile check was removed.

## Coverage against the two design indices

- **116 tests, 90 distinct `Design:` tags, 0 files with tag/test mismatch, 0 dangling tags, 0 stub instances covered.**
- Queue A: **47 tests / 22 of 22** difficulty instances (0 stubs) — full coverage.
- Queue B: **69 tests / 68 of 70** testable corner instances (90 instances, 20 stubs).

## Skipped instances

Both are **non-unique-derivability** skips (not PRD silence); no placeholder, xfail or weakened assertion was emitted.

1. `Corner/state_machines/activation_without_attestation_fails_precondition` — the design asserts 422 `ERR_ACTIVATION_PREREQUISITES_NOT_MET`, but PRD §2.11 rung 7 derives 409 `ERR_INVALID_STATE_TRANSITION` for activation attempted from `DRAFT`. The PRD does not uniquely derive the asserted outcome.
2. `Corner/state_machines/accepting_a_parked_transfer_cannot_skip_release` — the design asserts `ERR_INVALID_STATE_TRANSITION`, but the PRD ladder derives `ERR_PARTICIPANT_SEND_FROZEN` for the same call.

## Adaptations made (design honoured, PRD authoritative)

- `Difficulty/dual_variant_calc/reconciliation_variance_provisional_vs_final_diverge` — split into two PRD-legal setups.
- `transfer_diverted_to_fallback_rail_during_declared_outage` — asserts PRD-derived `diverted_transfer_count` values rather than the design's flat `== 1`.
- `credit_transfer_during_declared_outage_rejected` — outage resolved at 13:06, since §3.9 requires `ended_at` strictly later than `started_at` (design had `ended_at == started_at`).
- `daily_aggregate_limit_exceeded_by_second_transfer` — asserts `daily_sent_amount_cents == 0`, because that counter only moves on settlement.
- `restricted_account_error_outranks_per_transaction_limit` — asserts `FRAUD_BLOCK_REVIEW` per §3.5, not the design's `FRAUD_BLOCK_AUTOMATIC`.
- `return_request_at_window_boundary_rejected` — two tests sharing the one verbatim tag, because the logical clock cannot rewind inside a single server lifetime.
- `segment_policy_listing_filters_and_paginates_with_envelope` — the three policies were given strictly decreasing `effective_from` so §3.1's "newest `effective_from` first" and the design's creation order agree; the design's `created_at ASC` claim was not asserted.
- `stale_participant_version_on_policy_supersede_rejected` — asserts `effective_to == 2026-08-03T00:00:00Z` **and** `superseded_at == 2026-08-03T13:00:00Z` per §3.2 (design conflated the two).
- `diversion_of_unparked_transfer_rejected` — `diverted_to_rail`/`diverted_at` appear nowhere in the PRD, so `rail == "INSTANT"` and `queued_at is None` stand in.

## Step 6: Generate implementation — 2026-09-03T17:50:00.000Z

The implementation is complete.

## Files written (`workspace/implementation/`, 3,799 lines of Python + launcher)

**Root:** `start.sh` (8, exec + guarded pip install), `requirements.txt` (1, Flask 3.0.3), `app.py` (60), `db.py` (90), `errors.py` (96), `response.py` (89), `middleware.py` (65), `validation.py` (135), `timeutils.py` (60)

**`routes/` (10 blueprints, 1,629 lines):** `__init__.py` (30), `helpers.py` (10), `system.py` (34), `participants.py` (287), `position_accounts.py` (156), `configuration.py` (153), `credit_transfers.py` (324), `fraud_reviews.py` (103), `request_for_payments.py` (225), `return_requests.py` (216), `settlement.py` (196), `outages.py` (125)

**`services/` (854 lines):** `constants.py` (97, all 31 globals + every enum set), `lookup.py` (135), `liquidity.py` (237, derived balance/reserved/available, banding, alerts, posture + two-step propagation, strict-stop waterfall, projection), `serializers.py` (263), `limits.py` (98), `fraud.py` (91), `fees.py` (55), `reconciliation.py` (138), `sweep.py` (72)

## Verification
- `python3 -m py_compile` clean on all 27 `.py` files; `__pycache__` removed.
- **54 / 54 endpoints** registered (dumped `url_map` and matched it one-for-one against the scaffold endpoint table).
- Smoke test on port 21574 exercised: unauthenticated 401, clock set, full enrollment ladder (DRAFT -> ATTESTATION_PENDING -> CERTIFICATION_TESTING -> CERTIFIED -> LIVE), prefunding, segment policy with OCC, customer account, origination -> acceptance -> settlement (ledger debit -1500, balance 199,998,500, available unchanged), duplicate cycle 409, cutoff + fee assessment, FINAL recon run (rail net / variance / outcome) driving CUTOFF -> RECONCILING, closure -> RECONCILED, full RFP negotiation loop (deliver -> REQUEST_AMENDMENT -> amend -> ACCEPT with `response_deadline_at = min(expiry, +30m)`), return lodgement -> honour (compensating INBOUND transfer + RETURN_CREDIT restoring the balance; original transfer's ledger list shows the debit then the credit), fraud auto-block at 85 and the FRAUD_HOLD path (score 65, queue_priority 2, SoD refusals, assign -> BLOCK cascade restricting the customer), outage declaration (posture OFFLINE), window conflict 409, resolution -> NORMAL, projection, sweep counts, scope 403, 404, 400 shape, pagination bounds and `meta` fields.
- Fresh-boot check on port 21575: store empty (`data: []`, `total_count: 0`), clock at the default `2026-08-01T00:00:00Z` — no seeding anywhere.
- Both smoke servers stopped by PID/port lookup only; ports 21574–21576 confirmed free, no broad pattern kill used.

## Design notes worth flagging
- PRD beat SCAFFOLD where they disagreed: threshold ordering accepts equal adjacent values; RFP amendment replaces amount + memo only (never extends `expiry_at`); a score >= 85 at origination creates no review and leaves the debtor ACTIVE.
- `ERR_ATTESTATION_INCOMPLETE` is required by PRD §3.1 but missing from both error catalogs — implemented at HTTP 422.
- Activation enforces `alert_tier == GREEN` (hard precondition in both documents) via `ERR_INVALID_STATE_TRANSITION`; the PRD's "live over an AMBER account" aside is treated as descriptive.
- Exactly one `Participant.version` bump per request: lifecycle routes re-derive posture with `bump_participant=False` then bump once.
- Global §2.11 ladder is normative over per-section prose ordering — e.g. cutoff checks the accepted-traffic state rung before the business-date temporal rung, and honour checks the stored-amount rung before the deadline rung.
- Honoured-return ledger entries carry `related_transfer_id` = the original transfer, so §3.6's "settlement debit followed by the compensating credit" holds on that transfer's ledger list.

**Orchestrator layout check (independent):** `test_helpers/` (9 files) and `test_suite/` (19 files) confirmed at the task root; `find workspace -name test_helpers -o -name test_suite` returns nothing; `workspace/implementation/start.sh` present. Steps 5 and 6 were launched in a single assistant message, so the impl generator could not see `test_suite/` (it did not exist at its spawn time).

## Step 7: Run tests and iterate — 2026-09-03T19:11:00.000Z

Clean 8-round parallel sweep achieved: **116 / 116 passed, 0 failed, 0 errors, 0 skipped in all 8 rounds.**

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each).

**Sweep 1 result:** 80/116 passed, 36 failures — fully deterministic (identical failure set in all 8 rounds, so no flakiness signal, no load artifacts, no setsid reaping).

**Tests deleted:** none. Every failing assertion traced to a PRD sentence; all 36 failures reduced to three test-artifact bugs.

**Fixes applied to `test_helpers/`:**

- `test_helpers/assertions.py` — added `assert_instant(actual, expected, field)` (plus `_parse_instant`, `datetime` import). PRD §2.4 pins *three fractional digits* on `created_at`/`updated_at`, while PRD §2.5 quotes the logical clock itself as `2026-08-01T00:00:00Z` with none; the PRD therefore does not pin a single wire spelling for clock-derived domain timestamps (`settled_at`, `delivered_at`, `response_deadline_at`, `queued_at`, `cutoff_at`, `effective_from`, `superseded_at`, `horizon_end`, …). The helper compares the *instant*, still exact to the millisecond, so the substantive rule stays fully asserted while the non-derivable serialization detail is dropped (STEP 1c partial-coverage split).
- `test_helpers/assertions.py` — `assert_credit_transfer_shape()`: dropped the required-field demands for `diverted_to_rail` and `diverted_at`. PRD §3.9 says a diversion "writes the supplied value into the transfer's `rail`" and names neither attribute anywhere in the document (STEP 1a: PRD silent), so no PRD-faithful serializer can be required to emit them.

**Fixes applied to `test_suite/`:**

- 59 assertion sites across 11 files (`test_03`, `test_04`, `test_07`, `test_08`, `test_11`, `test_12`, `test_13`, `test_14`, `test_15`, `test_16`, `test_17`) rewritten from `assert x["ts_field"] == "…Z"` to `assert_instant(x["ts_field"], "…Z", "ts_field")`, with `assert_instant` added to each file's import block. This was the single root cause of 33 of the 36 failures.
- `test_suite/test_03_state_machine_loops.py` — `test_third_amendment_round_is_refused_after_the_loop_runs_twice`: the test's setup issued a *third* `REQUEST_AMENDMENT` response at `amendment_round == 2` and expected it to succeed, but PRD §3.7 states verbatim "A `REQUEST_AMENDMENT` requires `amendment_round` to be strictly below 2". The PRD-faithful implementation correctly refused it with `ERR_AMENDMENT_ROUNDS_EXHAUSTED`, surfacing as "Setup step failed". Rewrote the closing act to assert the refusal on the response hop (the reachable third attempt) and the resulting terminal state `DELIVERED` / amount 4,000,000 / round 2 / unchanged `expiry_at`. The exact `error_id` assertion was preserved, not downgraded; imports adjusted (`rfp_response_payload`, `PAYMENT_OPERATOR_BETA`).

**Fixes applied to `implementation/`:** none. Every failure was a test-artifact defect; no PRD-required check was removed or weakened, and no non-PRD field or endpoint was added.

The 8 passing `results.{1..8}.json` files are left in place under `workspace/implementation/`.

**Orchestrator verification (independent):** all 8 `results.{1..8}.json` exist under `workspace/implementation/` (timestamped 19:11, ~35 KB each) and each parses to `total=116, passed=116, failed=0, errors=0, skipped=0`. The green claim is confirmed against the artifacts, not taken on report.

**Step 8 skip decision:** NOT skipped. Step 7 applied 2 `test_helpers/` fixes and 60 `test_suite/` assertion-site fixes, which mark PRD sites that do not uniquely determine behavior the implementation already chose (timestamp wire format; `diverted_to_rail`/`diverted_at` absence; RFP amendment-round ceiling on the response hop). Step 8 runs with the Step 7 entry inlined as `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T19:24:00.000Z

Done. Exactly one line of PRD.md needed pinning; the other two Step 7 items were pure test-artifact bugs against behavior the PRD already determines.

## Line counts
- `PRD.md`: 447 lines / 103,425 bytes
- `PRD_FINALIZED.md`: 447 lines / 104,714 bytes
- Line delta: 0 (0.0%); byte delta +1,289 (+1.25%). Single changed line: `80c80`. Both files still end on the same final error-table row (`| ERR_INSUFFICIENT_LIQUIDITY | 422 |`).

## Changes
- **§2.4 Resource Identity, Timestamps and Record Versions — revise — extended the three-fractional-digit ISO-8601-UTC-with-`Z` rendering from `created_at`/`updated_at` to *every* instant-valued field the API emits (named the full set incl. `settled_at`, `queued_at`, `delivered_at`, `response_deadline_at`, `effective_from`/`effective_to`/`superseded_at`, `started_at`/`ended_at`, `cutoff_at`/`closed_at`, `horizon_end`, `api_request_timestamp`), stated that a zero sub-second part still renders `.000` (so §2.5's `2026-08-01T00:00:00Z` surfaces as `2026-08-01T00:00:00.000Z`), that unset instants emit `null`, and that business-date fields stay `YYYY-MM-DD` — `implementation/timeutils.py:12-19` (`iso()`), consumed at `implementation/services/serializers.py:22-263` and `implementation/response.py:25`.**

## Items deliberately **not** patched
- **`diverted_to_rail` / `diverted_at`** (test_helpers `assert_credit_transfer_shape` fix): PRD §3.9 line 297 says only that a diversion "writes the supplied value into the transfer's `rail`", and names neither attribute; `implementation/services/serializers.py:credit_transfer` emits neither. PRD and impl already agree — the over-demand lived only in the helper. Adding a negative claim would be inventing prose.
- **Third `REQUEST_AMENDMENT` refusal** (test_03 rewrite): PRD §3.7 line 264 already states verbatim that `REQUEST_AMENDMENT` requires `amendment_round` strictly below 2, and line 265 that a third attempt is `ERR_AMENDMENT_ROUNDS_EXHAUSTED`. `implementation/routes/request_for_payments.py:176-180` (response hop) and `:211-215` (amendment hop) both enforce `>= MAX_AMENDMENT_ROUNDS` -> that error. Pure fixture bug; no PRD-side ambiguity.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant serialization**
- (a) **Subject:** the wire rendering of every instant-valued (and, by exclusion, date-valued) field in any response body, from any source — clock-derived, caller-supplied, or arithmetic-derived.
- (b) **Impl paths enumerated / read:**
  - `implementation/timeutils.py` — `iso()` (single formatter: hard-coded `%03d` milliseconds + `Z`, `None -> None`), `parse_instant()` (accepts `Z`/`z`/offset/naive, normalizes to UTC), `date_str()`, `parse_business_date()`, `utc_date()`, `plus_minutes()`.
  - `implementation/services/serializers.py` — read in full; all 13 serializers plus `projection()`. Confirmed every `*_at`, `effective_*`, `expiry_at`, `horizon_end` goes through `iso()`, and that `business_date`, `settlement_business_date`, `go_live_business_date` are emitted raw as date strings.
  - `implementation/response.py` — `_meta()` -> `api_request_timestamp: iso(now())`, shared by `object_response`, `created`, `error_response`, `list_response` (so the claim holds on error and list envelopes too, not just success objects).
  - `implementation/services/sweep.py` — `run()` return value: four integer counters only, no instants (so the sweep endpoint can't contradict the sentence).
  - `implementation/services/liquidity.py:195-236` — `projection()` returns a raw `datetime` for `horizon_end`, formatted by `serializers.projection()`; `liquidity.py:82-83,108` — alert creation (`escalated_at`/`cleared_at` seeded `None`) and ledger `business_date` via `date_str(now())`.
  - Grepped all of `routes/` + `services/` for `iso(`, `date_str(`, `isoformat`, and dict literals with `_at` keys: every `_at` write in `routes/outages.py:92-93`, `routes/request_for_payments.py:77-81`, `routes/credit_transfers.py:155-158,182`, `routes/return_requests.py:81,174-177`, `routes/settlement.py:36-40`, `routes/configuration.py:102,142`, `routes/participants.py:62,162-189` stores a `datetime` or `None` (or, for `go_live_business_date`, the validated `YYYY-MM-DD` string) — never a pre-formatted instant string, so no path bypasses `iso()`.
  - `implementation/routes/system.py` — `POST /_clock/set_current_utc` returns `{}` and `db.clock` is never serialized directly, so the §2.5 clock literal is only observable through derived fields; this is why the new sentence talks about fields *derived from* the clock rather than about the clock's own representation.
- (c) **Wording adjustments made:** (1) scoped the universal claim to "instant-valued field … in a response body" and added the explicit `YYYY-MM-DD` carve-out, so the three-digit rule cannot be misread onto `business_date` / `settlement_business_date` / `go_live_business_date`; (2) added "regardless of whether the value was read from the logical clock, supplied by the caller, or computed by adding minutes to either" to cover caller-supplied `expiry_at`/`started_at`/`ended_at` and the `+30`/`+15`/`+120`/`+1440`-minute derivations, all of which share the one formatter; (3) added the `null` clause to match `iso(None) -> None`; (4) framed §2.5's `2026-08-01T00:00:00Z` as the *instant* and generalized to "instants quoted elsewhere in this document without a fractional part" rather than declaring §2.5's literal wrong, so no other quoted example becomes a contradiction; (5) mentioned `api_request_timestamp` as "the envelope's own" rather than as a §2.2-only example, since `_meta()` is shared by every envelope kind including errors and lists.

**Orchestrator verification (independent):** `wc` confirms PRD.md 447 lines/103,425 B and PRD_FINALIZED.md 447 lines/104,714 B; `diff` reports exactly `80c80` (one changed line, no additions or deletions); `tail` confirms PRD_FINALIZED.md still ends on the complete `| ERR_INSUFFICIENT_LIQUIDITY | 422 |` row. Not truncated.

## Step 9: Complete PRD — 2026-09-03T20:09:00.000Z

**Orchestrator decision (recorded per AUTONOMY):** Step 9 was run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` rather than as a single subagent. A single subagent scanning 27 impl modules against a 100 KB PRD reliably runs out of working context and returns a byte-identical file — i.e. the scan silently never happens. Partitioning by implementation file gives each pass a slice it can actually walk exhaustively, and the per-pass non-empty-diff sanity check makes a no-op scan detectable. Slices: Pass A = infrastructure + participants/position_accounts/configuration + constants/lookup/liquidity/serializers; Pass B = credit_transfers/fraud_reviews/request_for_payments + limits/fraud; Pass C = return_requests/settlement/outages + fees/reconciliation/sweep. Passes B and C were told not to re-copy the file and not to revert earlier wording.

### Pass A (infrastructure + onboarding/positions/configuration)

- `PRD_FINALIZED.md`: 447 lines / 104,714 chars -> `PRD_COMPLETED.md`: 448 lines / 112,802 chars (+1 line, +8,088 chars). Heading count unchanged at 29; error table grew 60 -> 61 rows.
- **ambiguity-pins: 18; mismatch-revisions: 2.**
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical rail clock, not host wall time — `response.py:25`
- §2.3 — revise — ambiguity — out-of-range/non-integer `limit`/`offset` are rejected with `ERR_INVALID_REQUEST`, not clamped; empty string = default — `response.py:46-68`
- §2.3 — revise — ambiguity — equal-sort-key ties broken by server creation order, never by `id`; list filters are exact string matches so an out-of-enum filter yields an empty page rather than 400 — `db.py:80-82`, `participants.py:252-284`
- §2.5 — revise — ambiguity — instant parsing accepts `Z`/numeric-offset/zoneless (normalised to UTC), unparseable -> `ERR_INVALID_REQUEST`; clock set returns empty `data` — `timeutils.py:21-33`, `system.py:28`
- §2.6 — revise — ambiguity — one posting advances account `version` by exactly 1 even when it also rewrites `alert_tier`/opens an alert; a fresh account is at `version` 1 — `liquidity.py:96-116`, `position_accounts.py:47-60`
- §2.9 — revise — ambiguity — a request that both hops the lifecycle and moves the posture bumps `Participant.version` once, not twice — `liquidity.py:182-200`, `participants.py:191-192`
- §2.11 rung 3 — revise — ambiguity — directly-named participant: scope before existence (403 even if absent); transitively-owned path record resolved first (404 before 403); absent body reference falls through to rung 5 — `position_accounts.py:66-67`, `configuration.py:32-36`
- §2.11 rung 5 — revise — ambiguity — optional field explicitly `null` == omitted; required `null` == missing; absent/unparseable body read as `{}`, non-object body refused — `validation.py:15-21,37-127`
- §2.11 rung 8 — revise — mismatch — `ERR_ATTESTATION_INCOMPLETE` added last to the compliance rung, so a non-`DRAFT` attestation gets `ERR_INVALID_STATE_TRANSITION` first — `participants.py:102-111`
- §3.1 — revise — ambiguity — non-`CERTIFIED`, below-minimum balance and non-`GREEN` tier are all `ERR_INVALID_STATE_TRANSITION`; no account at all -> `ERR_ACTIVATION_PREREQUISITES_NOT_MET` — `participants.py:164-188`
- §3.1 — revise — ambiguity — `go_live_business_date` format-checked only, never compared to the clock — `participants.py:162-163`
- §3.1 — revise — ambiguity — withdrawal refusal is `ERR_INVALID_STATE_TRANSITION`; in-flight test reads only own `OUTBOUND` transfers — `participants.py:222`
- §3.1 — revise — ambiguity — segment-policy list tie-break (newest `created_at`, then newest creation order); customer-account and outage lists ascending; "scoped to it" excludes `NETWORK_WIDE` — `participants.py:255,271,281-284`
- §3.2 — revise — ambiguity — daily aggregate < per-transaction -> `ERR_INVALID_REQUEST` on rung 5, ahead of version pin / `LIVE` / overlap — `configuration.py:48-52`
- §3.2 — revise — ambiguity — only non-superseded incumbents are overlap-tested; a new window may overlap a superseded one — `configuration.py:69-74`
- §3.2 — revise — ambiguity — the supersede flag reaches only an open-ended incumbent whose `effective_from` <= newcomer's and bumps that incumbent's `version`, else still `ERR_POLICY_WINDOW_OVERLAP`; inert when nothing qualifies — `configuration.py:76-90`
- §3.2 — revise — ambiguity — `fraud_risk_baseline` outside 0-100 -> `ERR_INVALID_REQUEST` — `configuration.py:121-123`
- §3.3 — insert — ambiguity — thresholds non-negative (zero legal; `floor_cents` 0 => never `BREACH`), opening strictly positive, checked before threshold ordering — `position_accounts.py:27-36`
- §3.3 — revise — ambiguity — operator `entry_type` set is the three-value set; `TRANSFER_DEBIT`/`FEE_DEBIT` -> `ERR_INVALID_REQUEST` on rung 5 — `position_accounts.py:76`, `constants.py:56`
- §3.3 — revise — ambiguity — `escalated_at` survives acknowledgement; SoD compares only the officer captured when that alert row opened — `position_accounts.py:147-151`, `liquidity.py:61-93`
- §5 preamble — revise — mismatch — unrouted path/undeclared method -> `ERR_INVALID_REQUEST` with transport status 404/405, not 400 — `app.py:40-46`
- §5 table — insert — mismatch — added missing `| ERR_ATTESTATION_INCOMPLETE | 422 |` row — `errors.py:45`
- Verified-already-pinned (no edit): ledger identity §2.8, band thresholds §2.9, alert emit/retire dedupe §2.9, park/release waterfall two-step and strict-stop §2.9, projection formula and nine response fields §3.3, ledger-entry absence of `updated_at`/`version` §2.4.

### Pass B (origination, fraud review, RFP)

- 448 lines / 112,802 chars -> 448 lines / 118,971 chars (16 lines touched, 19 in-paragraph edits).
- **ambiguity-pins: 18; mismatch-revisions: 1.**
- §3.4 — insert — ambiguity — rung-4 order among body references (`originator_participant_id` -> `customer_account_id` -> `rfp_id`); the rung-6 version pin is skipped entirely when the participant holds no position account — `credit_transfers.py:42-47,61`
- §3.4 — insert — ambiguity — `receiver_routing_number` trimmed before the nine-digit test and stored trimmed — `validation.py:130-135`
- §3.4 — insert — ambiguity — `daily_sent_amount_cents` derived per read against the clock's business date, so advancing past midnight returns it to 0 — `limits.py:50-66`
- §3.4 — insert — ambiguity — the position account's `version` stays advanced even when the send is immediately fraud-rejected; both fraud branches happen inside the creating request so the transfer returns at `version` 1 — `credit_transfers.py:163,169-173`
- §3.4 — insert — ambiguity — the cascade-created `FraudReview` also has `assigned_reviewer_user_id`, `final_fraud_score`, `decision_rationale` null — `credit_transfers.py:174-184`
- §3.4 — insert — ambiguity — `ParticipantAdmin` transfer listing: another participant in the originator filter is `ERR_PARTICIPANT_SCOPE_VIOLATION`; no filter is silently narrowed to its own — `credit_transfers.py:200`
- §3.5 — insert — ambiguity — a `RELEASED`/`BLOCKED` review re-decided is `ERR_INVALID_STATE_TRANSITION` (only `QUEUED` yields `ERR_FRAUD_REVIEW_NOT_ASSIGNED`) — `fraud_reviews.py:47-53`
- §3.5 — insert — ambiguity — a release blocked by a recomputed score >= 85 is `ERR_INVALID_STATE_TRANSITION` and writes nothing — `fraud_reviews.py:68-73`
- §3.6 — insert — ambiguity — all four acceptance preconditions fail as `ERR_INVALID_STATE_TRANSITION`; `SETTLED` is the one `ERR_TRANSFER_IRREVOCABLE` case — `credit_transfers.py:228-239`
- §3.6 — insert — ambiguity — the transfer's `version` advances by exactly 1 across the whole five-record settlement — `credit_transfers.py:262-265`
- §3.7 — insert — ambiguity — requestor and debtor's bank are never compared, so same-bank requests are permitted — `request_for_payments.py:53-70`
- §3.7 — insert — ambiguity — requesting side model-tested first; debtor's bank tested for model capability only; only `OFFLINE` blocks the requestor; requestor reference resolves first — `request_for_payments.py:34-68`
- §3.7 — insert — ambiguity — delivery error mapping: `ERR_PARTICIPANT_NOT_LIVE`, then `ERR_INVALID_STATE_TRANSITION` for both wrong-status and reached-expiry (delivery never raises `ERR_RFP_EXPIRED`), then the model code; posture not read — `request_for_payments.py:134-144`
- §3.7 — insert — ambiguity — any `PaymentOperator` may respond; caller never compared to debtor's bank or requestor — `request_for_payments.py:155`
- §3.7 — **revise** — **mismatch** — "it becomes payable exactly once that way" replaced: fulfilment writes nothing back to the request (stays `ACCEPTED`, same `version`, no consumed marker), so a second origination naming the same accepted request is not refused; also pinned that `ERR_CUSTOMER_ACCOUNT_RESTRICTED` outranks an elapsed deadline on `ACCEPT` — `credit_transfers.py:96-107`, `request_for_payments.py:167-174`
- §3.7 — insert — ambiguity — a `decline_reason_code` sent with `ACCEPT`/`REQUEST_AMENDMENT` is neither validated nor stored — `request_for_payments.py:160-161`
- §3.7 — insert — ambiguity — an omitted/null `memo` on amendment retains the existing memo; acting operator not checked against the requestor — `request_for_payments.py:201`
- §3.7 — insert — ambiguity — `ParticipantAdmin` may read/list a request when it owns either side; unfiltered listing narrows to both-sides ownership — `request_for_payments.py:94-97,109-123`
- §3.9 (diversion sentence only) — insert — ambiguity — no matching `DECLARED` covering event, or a supplied rail of `NONE`, is `ERR_INVALID_STATE_TRANSITION`; an `ACCEPTED` transfer draws the same code because the queued test precedes the `irrevocable_at` test — `credit_transfers.py:281-294`
- No Pass A wording reverted. `services/fraud.py` needed no change (§3.4/§3.5 already pin the four terms, clamp-then-multiply-then-cap, reason-code order, weight 3 / free 5 / 1,440-minute window, self-exclusion).

### Pass C (returns, settlement, outages, fees, reconciliation, sweep)

- 448 lines / 118,971 chars -> **448 lines / 127,948 chars** (+8,977). All 17 changed lines fall inside §3.8/§3.9/§3.10 (lines 275-319).
- **ambiguity-pins: 21; mismatch-revisions: 2.**
- §3.8 — insert — ambiguity — body-reference order (`requested_by_participant_id` before `credit_transfer_id`), `narrative` unbounded — `return_requests.py:28-35`
- §3.8 — insert — ambiguity — omitted `narrative` stored null — `return_requests.py:82`
- §3.8 — insert — ambiguity — the whole honour cascade advances request `version` and original transfer `version` by exactly 1 each — `return_requests.py:152-154,183`
- §3.8 — insert — ambiguity — the compensating row's unstated fields (`segment_policy_id` copied, `settled_at` = clock, `exception_status` NONE, empty `fraud_reason_codes`, seven null fields, `version` 1) — `return_requests.py:157-181`
- §3.8 — **revise** — **mismatch** — the `RETURN_CREDIT` entry's `related_transfer_id` points at the **original** transfer, not the compensating row; plus `business_date` and null `reference` — `return_requests.py:189-191`
- §3.8 — insert — ambiguity — with no position account the honour still succeeds, last three hops skipped — `return_requests.py:187-193`
- §3.8 — insert — ambiguity — `ParticipantAdmin` may read/list either side; unfiltered list narrows to both-sides rows; ascending arrival order — `return_requests.py:95-99,112-131`
- §3.9 — insert — ambiguity — any non-empty body `participant_id` is resolved on rung 4 even for `NETWORK_WIDE` (then discarded); `started_at` never compared to the clock; a supplied `ended_at` does not resolve — `outages.py:62-74`
- §3.9 — insert — ambiguity — a null `ended_at` is infinite on either side of the conflict test — `outages.py:39-54`
- §3.9 — insert — ambiguity — `NETWORK_WIDE` covers every participant on the register regardless of `enrollment_status`, ascending `created_at` — `outages.py:26-30`
- §3.9 — insert — ambiguity — diverted count written inside creation, event returned at `version` 1; participant `version` moves only on a real posture change — `outages.py:98-102`
- §3.9 — insert — ambiguity — `EXPIRED` is terminal and the sweep never runs a release pass over freed headroom — `sweep.py:37-65`
- §3.9 — insert — ambiguity — rung-5 interval outranks rung-7 state; event `version` +1; conflict test not re-run; `diverted_transfer_count` preserved — `outages.py:105-125`
- §3.10 — insert — ambiguity — `business_date` must be plain `YYYY-MM-DD`; rung 10 beats rung 11 (future+duplicate -> `ERR_BUSINESS_DATE_NOT_REACHED`); any `ParticipantAdmin` may read any cycle — `settlement.py:22-33,46-50`
- §3.10 — insert — ambiguity — accepted-traffic scan matches by UTC date of `accepted_at`, skips null, spans all participants; state refusal outranks the temporal one — `settlement.py:59-73`
- §3.10 — insert — ambiguity — fee entry has null `related_transfer_id`/`reference`; `business_date` = clock at cutoff, so cutting a past date off later leaves the `FINAL` fee component at zero — `fees.py:46`, `reconciliation.py:67-77`
- §3.10 — **revise** — **mismatch** — `assessed_fee_total_cents` sums computed net fees, not posted entries (a `LIVE` participant with no position account still contributes); non-`LIVE` contributes nothing; cutoff bumps cycle `version` by 1 — `fees.py:31-55`, `settlement.py:76-77`
- §3.10 — insert — ambiguity — rung-7 cycle status precedes the rung-9 account check; `participant_id` resolved before `settlement_cycle_id`; no enrollment/posture/ownership test — `settlement.py:103-134`
- §3.10 — insert — ambiguity — both reconciliation sides matched on `originator_participant_id` — `reconciliation.py:9-23`
- §3.10 — insert — ambiguity — the `RECONCILING` tolerance test reads only the run just submitted; a within-tolerance run leaves the cycle untouched — `settlement.py:154-157`
- §3.10 — revise — ambiguity — runs page is the default ascending arrival order (only *within* a triple is that ascending `revision`); cycle `version` moves only on a status change; `ParticipantAdmin` transitive scope and silent filter narrowing — `settlement.py:165-196`
- §3.10 — insert — ambiguity — `LIVE` population read at closure time; vacuously satisfied with no `LIVE` participant — `reconciliation.py:133-138`
- §3.10 — insert — ambiguity — sweep runs four passes in the listed order, each ascending `created_at`; recompute once per participant after all passes in first-touch order; no ledger entry and no position-account `version` bump; `data` is exactly the four counters; an immediate repeat reports zeroes — `sweep.py:13-72`

### Pass C closing integrity check
- No `TODO`/`TBD`/`FIXME`/`XXX`/placeholder markers anywhere in the document.
- No duplicated sentences or fragment collisions from overlapping passes (programmatic sentence-multiset scan: zero repeats >60 chars).
- §5 error table: 61 rows, one per line, all `| ERR_X | NNN |` well-formed; cross-checked against `implementation/errors.py` — identical code set, zero status mismatches, no extras either way.
- File ends on the complete final row `| ERR_INSUFFICIENT_LIQUIDITY | 422 |`.

### Step 9 totals
- `PRD.md` 447 lines / 103,425 chars -> `PRD_FINALIZED.md` 447 / 104,714 -> `PRD_COMPLETED.md` **448 lines / 127,948 chars** (+23,234 chars over PRD_FINALIZED, +22.2%).
- **57 ambiguity-pins + 5 mismatch-revisions = 62 changes** across the three passes.

**Orchestrator verification (independent):** `wc -l -c` confirms 447/103,425, 447/104,714, 448/127,948; `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 103 changed lines (not byte-identical, so the scan genuinely ran); `cmp` confirms the files differ; `tail` confirms `PRD_COMPLETED.md` ends on the complete `| ERR_INSUFFICIENT_LIQUIDITY | 422 |` row. Pipeline complete.
