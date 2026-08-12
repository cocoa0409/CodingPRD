# Worklog — task_1105_corporate_actions_processing

## Step 1: Create task directory — 2026-08-10T15:15:00.000Z

Pre-assigned output folder `tasks/task_1105_corporate_actions_processing` with `workspace/` subdirectory already exists (verified on disk). Step 1 auto-index scan skipped per instructions.

## Step 2: Generate scaffold — 2026-08-10T16:10:00.000Z

Done. All three scaffold artifacts were generated for task 1105 (Corporate Actions Processing) at harder-than-expert depth, purely from the scenario text plus the skill spec — no sibling task directories were inspected.

**Output files (all verified on disk, non-empty, YAML-parseable):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/SCAFFOLD.yaml` — **1478 lines** (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **829 lines** (single top key `scaffold_difficulty_design`; 9 rules × ≥2 = **19 instances**)
- `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/SCAFFOLD_CORNER_DESIGN.yaml` — **1203 lines** (single top key `scaffold_corner_design`; **55 instances** across all 9 claim-taxonomy sections, 50 active + 5 `excluded_because` stubs)

**Design summary (harder-than-expert calibration):**
- 14 entities, 52 endpoints, 52 error codes, 11 state machines, 10 calculations, 12 ordered validation priorities, 7 roles — flat topology, `segregation_of_duties` role model (scrubber ≠ confirmer; filer ≠ decider), `ledger_reconciliation` × `compliance_audit` archetypes, layers: OCC, cascading side effects, dual-variant calc, scheduled actions.
- Difficulty anchors: TRADE_DATE vs SETTLED entitlement bases (1250→2500 vs 1000→2000 on identical lots); EVENT_TERMS vs MARKET_VALUE claim compensation (50000 vs 56000); merger odd-lot waterfall proration (mode a); per-lot floor-then-sum cash-in-lieu vs aggregate projection (30/5499 vs 31/2166 — mode b); single-pass rights oversubscription (mode c); cyclic event amendment and election withdraw→resubmit machines; depth-4 booking cascade into recon-break auto-resolution; half-open event windows vs closed statement-coverage intervals; share/basis and cash compensating invariants; inclusive deadline boundary (16:00:00Z pass / 16:00:01Z fail) vs 99-vs-100 odd-lot boundary.
- Two true-race OCC rules (`expected_event_version` on amendments and election submits), 412.
- Logical clock test endpoint with the mandatory fixed default `2026-05-01T00:00:00Z`.
- Every formula-derived assertion literal was pre-computed with Python (proration factor 0.3375→200000/80 sh; 0.3681→180000/64 sh; CIL 5499/2166; spin-off 0.1121→1121000/8879000; rights 150/250 with 600 retained; auto-claim 166650).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (764 calls scanned). Three initial FK-reachability findings were fixed by normalizing path params to `{id}` and adding an `auto_claim_id?` filter; forbidden-vocabulary grep is clean; grounds resolvability and cross-file name uniqueness verified by script.

## Step 3: Copy shared files — 2026-08-10T16:11:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1105_corporate_actions_processing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T16:30:00.000Z

PRD generation is complete and verified. The document was written to `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/workspace/PRD.md` (335 lines, 57,795 bytes, non-empty). The withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) and all sibling task directories were never opened.

**Document structure** (domain-derived, per the diversity rules):
- §1 Introduction — 2 paragraphs, business-context angle (desk risk, scrubbing, golden record)
- §2 Global Specifications — 10 subsections: RBAC (7 roles with identity prose: `AccountHolder` entity-backed to `Account`, six opaque roles), §2.2 API Response Structure (byte-identical to the verbatim source block — verified programmatically), Pagination (limit default 10, min 1, max 100, offset 0, `created_at` ascending), The Desk's Logical Clock (default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`), Common Resource Properties (with the three immutable record types — `SourceNotification`, `EventAmendment`, `BookingLine` — explicitly carrying only `id` + `created_at`), Money/Quantities/Rounding (integer cents, 4dp quantities, three fractional policies with the 1666.5-cent illustration), OCC, Segregation of Duties, Derived Balances/Immediate Consistency, Validation Order (explicit 12-step priority sequence + left-to-right existence + all 13 not-found codes)
- §3 Business Logic — 9 subsections organized chronologically along the desk pipeline (setup → intake → scrubbing → confirm/amend/cancel → elections → capture/booking → reversal/completion → claims → custodian reconciliation), with all 10 calculation formulas rendered as precise pseudocode-free prose (pinned per-lot floor-then-sum, merger waterfall with 100-share odd-lot threshold, single-pass rights oversubscription, spin-off basis split with percentage-first rounding, both claim compensation variants, zero-tolerance recon), constants embedded in context (two-day settlement lag, 250,000-cent claim cap, 30-day claim window)
- §4 Endpoint table — 52 rows, 4 columns, paths and roles verified equal to the scaffold in order and value
- §5 Error catalogue — 52 rows, 2 columns, all HTTP statuses match the scaffold (incl. 402 for `ERR_COMPENSATION_POOL_EXHAUSTED` and 400 for `ERR_INVALID_ELECTION_OPTION`)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 81 required, 81 present, 0 missing
- endpoints[].request_body: 50 required, 50 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
- endpoints[].path_params: 1 required ({id}), 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (explicit 12-step global order in §2.10, plus per-endpoint ordering restated for election submit and claim decide), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (amendments + elections each named with expected_event_version, ERR_STALE_EVENT_VERSION, HTTP 412; no race-timing framing), 0 missing
- state_machines[].transitions: 41 checked across all 11 state machines, 41 fully expressed (from/to states, preconditions with error ids, side effects incl. all 5 booking cascade links and the exact-restore reversal), 0 missing
- calculations[]: 10 checked, 10 fully expressed (variants, constants, pinned evaluation/rounding orders), 0 missing
- validations[] conditions: 12 priority groups checked, all matchable to their error_id in §2/§3 prose; all 52 error ids appear in backticks, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed (multi-endpoint scopes like the three election ownership checks and the four temporal guards enumerated), 0 missing
- entities[].fields[] structured content: 81 checked, 81 reconstructible (defaults, null-until-settled/approved semantics, closed-interval coverage, 4dp types), 0 missing
- sibling-branch symmetry: 8 groups checked (cancel from DRAFT vs CONFIRMED/AMENDED, confirm from DRAFT vs AMENDED, EVENT_TERMS vs MARKET_VALUE, three fractional policies, three recon line kinds, odd-lot vs round-lot merger branches, SETTLED vs MISSED booking outcomes, manual resolve vs write-off), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 597
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional quality checks passed: §2.2 byte-identical to `section-2.2-response-structure.md`; no fuzzy/approximating words anywhere; no operator symbols (`==`, `>=`, `+=`, etc.) in prose; all 7 role names and all 70 enum/state values present in backticks.

## Step 5: Generate unit tests — 2026-08-10T16:55:00.000Z

Done. Summary:

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/`):
- `test_helpers/` — 9 files: `__init__.py` (barrel), `types.py` (14 entities, immutable records correctly omit `updated_at`/`version`), `api_client.py` (all 52 endpoints), `api_errors.py` (52 error IDs + HTTP map registered), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (with `make_account_holder_headers(account.id)` for the entity-backed role), `fixtures.py` (composite lifecycle helpers: scrubbed/confirmed events, booked split, missed-entitlement+claim, merger/rights contexts, recon-break setup).
- `test_suite/` — 15 files: `conftest.py` + 14 test files grouped by concern (basis variants, booking calculations, state cycles, cascades, priority/boundaries, cross-entity gates, window overlap, reversal invariants, entity basics, state guards, calculation corners, validations, endpoints/RBAC, concurrency/derived).

**Coverage:**
- Queue A (Difficulty): all 19 instances, exactly 2 tests each (38 tests).
- Queue B (Corner): all 50 non-stub instances, ≥1 test each (50 tests). The 5 `excluded_because:` stubs were not translated; all cross-references resolve to real difficulty instances.
- Total: 88 test functions, 69/69 non-stub instances covered, 0 skipped instances, no `skip`/`skipif`/`xfail` markers.

**Verification:** `python3 -m py_compile` passes over all 24 `.py` files. Every test docstring carries a verbatim PRD citation (normalized-whitespace grep over PRD.md: 0 misses) and ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real instance (0 tag problems).

One notable repair during generation: the PRD wraps identifiers in backticks, so initial docstring citations were rewritten to match PRD text exactly (including backticks and `**bold**` markers in §2.5 bullets); the final audit confirms full verbatim compliance.

(Note: the first Step 5 subagent attempt returned a truncated plan with zero files on disk; it was re-spawned with the same spec and completed fully. Orchestrator verification: 24 py files, 88 test functions, 88 Design tags, all compile.)

## Step 6: Generate implementation — 2026-08-10T16:45:00.000Z

Implementation complete and verified. Summary below.

## What was built

A Python + Flask implementation of the Corporate Actions Desk API at `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/workspace/implementation/`:

- `start.sh` — executable, guards the pip install (`python3 -c "import flask"` check), `exec python3 app.py` in foreground
- `app.py` — Flask app factory (static folder disabled so the route table is exactly the API), error handlers, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict-of-dicts store, 14 tables, starts completely empty (no seeding anywhere); creation-order sequence for the PRD's created-at-ascending sort
- `util.py` — logical clock (default `2026-05-01T00:00:00Z`, never wall-clock), 3-fractional-digit ISO timestamps, UUID ids, `req_*` request ids, Decimal helpers (`round4_half_up`, `floor4`, per-event `fractional_policy` cent rounding)
- `errors.py`, `helpers.py` — full error catalog with exact HTTP statuses (incl. 402 pool exhaustion, 412 OCC), the `meta`/`response_type`/`data` envelope, pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, range 1–100), `X-User-ID`/`X-User-Role` auth with per-endpoint RBAC for all 7 roles
- `domain.py` — derived account balances (§2.9), TRADE_DATE vs SETTLED_BASIS snapshots (2-day settlement lag), aggregate projection per event type, per-type terms coherence
- `booking.py` — booking cascade: per-lot floor-then-sum splits, spin-off FMV basis split (4dp pct first, remainder to parent), merger odd-lot/round-lot waterfall with floor4 factor, rights single-pass oversubscription, exact prior-value reversal
- `recon.py` — synchronous statement reconciliation, POSITION_MISMATCH / CASH_MISMATCH / MISSED_ENTITLEMENT breaks, system-filed auto-claims
- `routes_setup.py`, `routes_events.py`, `routes_voluntary.py`, `routes_recon.py` — all 52 endpoints with §2.10 validation ordering (auth → RBAC → shape → existence → ownership → state → OCC → SoD → business → temporal → referential → fiscal)

## Verification results

1. **start.sh**: exists, executable (`-rwxrwxr-x`), foreground launcher with guarded install
2. **py_compile**: all 13 `.py` files pass
3. **Boot check**: `PORT=<port> bash start.sh` boots cleanly; curl confirmed envelope shape, auth 400/403s, clock set/echo, empty store on fresh boot (`total_count: 0` on list endpoints, no tracebacks)
4. **Route diff**: expected 52 from SCAFFOLD.yaml, actual 52 registered — `missing: []`, `extra: []`, EXACT MATCH (independently re-verified by orchestrator: 52 scaffold pairs vs 52 Flask routes, no missing, no extra)
5. **Behavioral smoke tests** (fresh process each): SPLIT end-to-end (scrub→MATCHED notifications, SoD 403, projection 100.5→150 shares/0.75 frac/2500¢ CIL, capture-before-record-date 422, book per-lot floors 150+0 with lot FULLY_SURRENDERED, complete, reverse restoring lots/cash exactly and entitlements SETTLED→FIRM with nulled booked fields); RIGHTS_OFFERING (ownership 403, quantity-exceeds 422, stale OCC 412, withdraw/resubmit seq increment, book-during-window 422, 80×500¢ debit, APPLIED election); CASH_DIVIDEND with FROZEN account (entitlement MISSED, claim→approve with pool reserve 50000→40000, pay credits 10000¢, MISSED→COMPENSATED); custodian statements (POSITION_MISMATCH and MISSED_ENTITLEMENT breaks, coverage overlap 409, non-custodian source 422); amendment OCC + SUPERSEDED/replacement re-projection chain; break resolve MANUAL + not-open 409.

One fix applied during testing: a missing `req_enum` import in `routes_recon.py` (surfaced as a 500 on break resolve) — fixed and re-verified.

## Step 7: Run tests and iterate — 2026-08-10T17:28:00.000Z

All 88 tests pass in all 8 parallel rounds.

## Summary

- **Iterations run**: 3
- **Tests deleted**: None
- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/test_helpers/factories.py` — `create_security_payload`: fixed CUSIP generator from `f"CUS{n:08d}"[:9]` (which truncated to the same 9-char `CUS000000` for all n) to `f"CUS{n:06d}"`, producing genuinely unique 9-char CUSIPs. PRD §3.1: "the ticker and the CUSIP are each unique across all securities" — the implementation was PRD-correct; the factory was generating colliding identifiers.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/test_helpers/fixtures.py` — `make_security` / `make_account`: changed from hardcoded defaults (`ticker="ACME"`, `account_number="A-1"`) to `None`-sentinel passthrough so the auto-unique factory defaults are used when the caller doesn't explicitly override. Composite fixtures that create multiple securities per test (e.g. `make_merger_event_confirmed`, `_setup_pair`) no longer collide on the PRD-required uniqueness constraint.
- **Fixes applied to `test_suite/`** (test bugs, fixed in place to be PRD-faithful):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/test_suite/test_14_concurrency_and_derived.py::TestOccAmendmentStaleVersion::test_stale_amendment_rejected_after_first_amendment` — PRD §2.10 fixes state preconditions (step 6) ahead of the OCC version match (step 7), so a stale-version amendment against an `AMENDED` event would correctly produce `ERR_EVENT_NOT_AMENDABLE`, not `ERR_STALE_EVENT_VERSION`. Inserted a PRD §3.4-sanctioned re-confirmation (`AMENDED → CONFIRMED`) between the first amendment and the stale-version attempt, so the state check passes and the OCC branch is exercised in isolation. Also added missing `validate_paginated` import.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/test_suite/test_10_event_state_guards.py::TestElectionVoidLockdown::test_withdraw_void_election_rejected` — PRD is silent on precedence between `ERR_EVENT_ALREADY_TERMINAL` (event is CANCELLED, §3.4) and `ERR_ELECTION_INVALID_STATE` (election is VOID, §3.5) when both hold for a withdraw. Relaxed to `validate_error_is_one_of([ERR_ELECTION_INVALID_STATE, ERR_EVENT_ALREADY_TERMINAL])` per the cardinal-rule exception for ERROR PRECEDENCE SILENCE.
- **Fixes applied to `implementation/`**: None — the implementation was PRD-correct in every diagnosed case.

**Final state**: 88/88 passed × 8/8 rounds.

(Orchestrator verification: all 8 `results.{1..8}.json` files present on disk; each reports passed=88, total=88, failed=0.)

## Step 8: Finalize PRD — 2026-08-10T17:35:00.000Z

The edit is applied and the diff is clean. Submitting the summary.

---

## Summary

**File counts**
- `PRD.md`: 335 lines
- `PRD_FINALIZED.md`: 335 lines (0% line-count delta; single sentence appended in-place on line 169)

**Changes (one total)**

- **§3.5 — insert** — Added a precedence sentence pinning that for `withdraw` and `resubmit`, the event's terminal-state check fires before the election's state check, so a request against a `COMPLETED`/`CANCELLED` event whose election is also in the wrong state returns `ERR_EVENT_ALREADY_TERMINAL`, not `ERR_ELECTION_INVALID_STATE` — `implementation/routes_voluntary.py:138-141` (withdraw) and `implementation/routes_voluntary.py:159-165` (resubmit), both via `event_terminal_guard` at `implementation/domain.py:273-276`.

**Per-edit pre-edit search log**

- **Edit 1 (the only edit)**
  - (a) Subject: error precedence between `ERR_EVENT_ALREADY_TERMINAL` and `ERR_ELECTION_INVALID_STATE` on the election withdraw/resubmit endpoints when both conditions hold simultaneously.
  - (b) Impl paths enumerated and read/grepped:
    - `implementation/routes_voluntary.py:128-146` — `withdraw_election` (calls `event_terminal_guard` at L138, then election-state check at L139-141).
    - `implementation/routes_voluntary.py:149-178` — `resubmit_election` (calls `event_terminal_guard` at L159, then `EVENT_NOT_ACCEPTING_ELECTIONS` at L160-162, then election-state check at L163-165).
    - `implementation/domain.py:273-276` — `event_terminal_guard` definition (raises `ERR_EVENT_ALREADY_TERMINAL` when `status ∈ {COMPLETED, CANCELLED}`).
    - `grep -rn "ERR_EVENT_ALREADY_TERMINAL\|ERR_ELECTION_INVALID_STATE\|event_terminal_guard" implementation/` — confirmed the only other callsites of `event_terminal_guard` are in `routes_events.py` (confirm/amend/cancel/capture/book/complete), which operate on the event itself with no election-state check, so the new sentence cannot mis-describe them. `ERR_ELECTION_INVALID_STATE` is raised only in `routes_voluntary.py` (withdraw/resubmit).
  - (c) Wording adjustment: the sentence is explicitly scoped to "withdrawal and resubmission" rather than claiming a generic event-terminal-before-state rule across all endpoints, even though the impl happens to do the same elsewhere — this keeps the wording consistent with every enumerated path while not over-claiming about endpoints whose PRD text already pins their behavior in §3.4/§3.6/§3.7.

**Step-7 items requiring no PRD patch (and why)**

- `test_helpers/factories.py` CUSIP generator — pure fixture bug; PRD §3.1 already pins per-field uniqueness ("the ticker and the CUSIP are each unique across all securities"), and the impl enforces it. No PRD silence.
- `test_helpers/fixtures.py` `None`-sentinel passthrough — pure fixture bug; no PRD implication.
- `test_14_concurrency_and_derived.py` stale-amendment precondition fix — PRD §2.10 already fixes "sixth, state preconditions" ahead of "seventh, the optimistic-concurrency version match"; the impl follows it (`routes_events.py` amendment path checks `ERR_EVENT_NOT_AMENDABLE` before `ERR_STALE_EVENT_VERSION`). No PRD silence.
- No implementation fixes were applied in Step 7 — final state 88/88 × 8/8 rounds.

## Step 9: Complete PRD — 2026-08-10T17:45:00.000Z

PRD_COMPLETED.md finalized: 335 lines in both files; +3,963 chars (58,142 → 62,105). 15 edits applied: 12 ambiguity-pins, 3 mismatch-revisions.

- §2.1 — revise — ambiguity — whitespace-only headers → 400; unrecognized role values → 403; X-User-ID whitespace-stripped — helpers.py:64-74
- §2.3 — revise — ambiguity — non-integer limit/offset, out-of-range limit, negative offset → ERR_INVALID_REQUEST 400 — helpers.py:197-221
- §2.4 — revise — ambiguity — missing/malformed to_iso8601 → ERR_INVALID_REQUEST 400; current_utc echoed as ISO 8601 UTC with trailing Z — routes_setup.py:22-36, util.py:69-71
- §2.9 — revise — mismatch — cash balance = opening + cash deltas of lines on POSTED bookings + PAID claim compensation; reversal posts no inverse lines (reversed booking's lines drop out) — domain.py:28-59, booking.py:427-428
- §3.1 — revise — ambiguity — duplicate ticker/cusip and duplicate account_number → ERR_INVALID_REQUEST; invalid security/account status transition → ERR_INVALID_REQUEST — routes_setup.py:50-53, 87-91, 108-111, 157-159
- §3.2 — revise — ambiguity — rejecting a non-RECEIVED notification → ERR_INVALID_REQUEST 400 — routes_setup.py:350-352
- §3.3 — revise — mismatch — "live mandatory event" = any non-CANCELLED mandatory event (COMPLETED/BOOKED still occupy their window) — routes_events.py:94-105
- §3.3 — revise — ambiguity — terms-internal security refs must exist (ERR_SECURITY_NOT_FOUND); negative compensation_pool_cents / bad claim_compensation_basis → ERR_INVALID_REQUEST — routes_events.py:52-58, 77-81
- §3.3 — revise — ambiguity — election_deadline must be strictly before midnight UTC at end of payable date — routes_events.py:66-70
- §3.4 — revise — ambiguity — amended_terms re-validated for type coherence incl. terms-internal securities — routes_events.py:221-226
- §3.4 — revise — ambiguity — confirm from other non-terminal states → ERR_INVALID_REQUEST 400; terminal → ERR_EVENT_ALREADY_TERMINAL — routes_events.py:179-182
- §3.4 — revise — ambiguity — cancel-from-BOOKED performs no unwind: booking stays POSTED, SETTLED/MISSED entitlements and lot/cash mutations untouched — routes_events.py:279-297
- §3.5 — revise — ambiguity — non-positive/non-integer election quantity → ERR_INVALID_REQUEST 400 — routes_voluntary.py:53-58
- §3.6 — revise — mismatch — odd-lot CASH honored at shares × cash_per_share_cents rounded half-up to whole cents; prorated odd-lot gets min(full, remaining); merger conversion CIL valued at cash_per_share_cents rounded half-up (merger terms carry no price_per_share_cents/fractional_policy, so "exactly as in a split" corrected); surrendered parent lots zeroed with unconverted basis remainder left on them; new lot only when it carries shares or basis — booking.py:149-254
- §3.7 — revise — ambiguity — reversal returns event BOOKED→CONFIRMED only while still BOOKED; a cancel-from-BOOKED event stays CANCELLED — booking.py:462-464
- §3.9 — revise — ambiguity — cash_cents without event_id treated as a position line (cash_cents ignored); CASH_MISMATCH break carries expected_quantity zero / reported_quantity = line quantity; entitlement line compares against latest non-SUPERSEDED entitlement's entitled_shares (zero if none); auto-claim amount = |share diff| × price_per_share_cents rounded half-up (zero when no per-share price); auto-filed claims bypass ownership, filing window, and amount cap — recon.py:33-113

File: /home/ubuntu/github/CodingPRD/tasks/task_1105_corporate_actions_processing/workspace/PRD_COMPLETED.md

(Note: the first Step 9 subagent completed its analysis but was truncated before applying edits — PRD_COMPLETED.md was byte-identical to PRD_FINALIZED.md. A bounded retry subagent re-verified the candidate gaps against implementation/ and applied 15 edits; orchestrator verified the file now differs, +3,963 chars.)
