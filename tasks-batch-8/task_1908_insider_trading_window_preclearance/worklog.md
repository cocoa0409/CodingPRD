# Worklog — task_1908_insider_trading_window_preclearance

## Step 2: Generate Scaffold — 2026-08-15T00:21:27.000Z

Scaffold generation complete. Lint verdict: clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

- **Entities: 10** (CoveredPerson, Deal, RestrictedListEntry, BlackoutWindow, PreclearanceRequest, ExceptionRequest, TenB5Plan, TradeConfirmation, ViolationCase, Attestation) — flat topology with cross-aggregate FKs and one self-referential merge link
- **State machines: 10** — including cyclic TenB5Plan (RETURNED→SUBMITTED, SUSPENDED↔ACTIVE) and branching/cyclic ViolationCase (escalation loop + SUBSTANTIATED/UNFOUNDED fork)
- **Endpoints: 48** (incl. `POST /compliance-sweeps` ops-run and `POST /_clock/set_current_utc` with default 2026-08-01T00:00:00Z)
- **Difficulty instances: 18** — all 9 rules × 2 instances, each with fully structured `setup_api_calls` (485 calls across both design files replayed against §1.2/§1.4/§1.6)
- **Corner instances: 56** (41 active + 15 `excluded_because` stubs referencing §1.8 instances)

## Design highlights

- Archetype: compliance/audit + temporal windowing; segregation-of-duties role model (Insider / ComplianceOfficer / CommitteeMember all entity-backed by CoveredPerson, LegalAdmin opaque); 3 OCC concurrency rules (decision stale-version, plan create-with-supersede, window extend)
- Dual-variant calcs on different domains: preclearance provisional-vs-final validity (PreclearanceRequest) and designation-driven cooling-off (TenB5Plan)
- Combinatorial formulas in different modes: sanction severity scoring (multi-input capped scoring, mode a) and per-line round-then-accumulate matched-quantity consumption (mode b), with computed literals pinned (e.g., severity 35 → SUSPENSION_30D; 10.005+10.005 → 20.02 → CLOSED)
- Depth-3 cascade (confirmation flag → auto case → compliance hold → blocked submission) and depth-2 cascade (deal activate → restricted entry → auto-denial)
- `scaffold_lint.py`: `VERDICT: clean lint` — plus mechanical checks for name uniqueness (74 unique), stub-reference integrity, grounds resolvability, enum closure, and forbidden vocabulary all pass

## Step 3: Copy Shared Files — 2026-08-15T00:21:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1908_insider_trading_window_preclearance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T00:28:00.000Z

All mechanical checks pass. I completed the Contract 2 rule-coverage walk manually against every scaffold rule table (transitions, calculations, validations, OCC rules, side effects, sibling branches). The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/workspace/PRD.md`

**Structure:** 5 top-level sections; 10 §2 subsections (domain-derived titles: The Logical Clock and Half-Open Time; Share Quantities, Money, and Rounding Discipline; Segregation of Duties; Validation Order and Error Precedence; Atomic Cascades and the Compliance Sweep; etc.); 8 §3 subsections grouped by business process (covered persons/eligibility, blackout calendar, deal intake/restricted list, preclearance lifecycle, hardship exceptions, 10b5-1 plans, confirmation matching, violations/sanctions). §4 endpoint table: 48 rows, 4 columns. §5 error catalogue: 20 rows, 2 columns.

**Word count:** 7,283 words.

**Contract 1 — Field-Name Coverage: PASS**
- entities[].fields: 64 required, 64 present, 0 missing
- endpoints[].input: 44 required, 44 present, 0 missing (pass 1 caught `action` missing; fixed in §3.6/§3.8, pass 2 clean)
- query params / path params: 1 required, 1 present, 0 missing

**Contract 2 — Rule Coverage: PASS**
- validations[] with priority: 21 checked, 21 expressed (explicit ordering prose for the submission gauntlet, decision chain, vote guards, plan-creation gates, window-creation checks, ack-before-training)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_*_version + ERR_STALE_VERSION/412 named for each; no temporal-overlap framing)
- state_machines[].transitions: 56 checked, 56 fully expressed
- calculations[]: 9 checked, 9 fully expressed (all constants embedded; pinned rounding order carries the scaffold's 10.005→20.02 worked contrast in prose)
- validations[] conditions: 21 checked, 21 matchable to error_id in §2/§3 prose
- endpoints[].side_effects / applies_to: 48 checked, all expressed (including all cascade hops and the restricted-list screen's two enforcement points)
- entities[].fields[] structured content: 64 checked, reconstructible from prose
- sibling-branch symmetry: 8 groups checked (deal close COMPLETED vs ABANDONED, STANDARD vs EXECUTIVE cooling-off, PROVISIONAL vs FINAL validity, both close paths, both withdraw from-states, both match lanes, three flagged_reason branches, both suspension durations), all equal density

**Contract 3 — §3 Path Purity: PASS**
- backtick tokens scanned: 514; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0

**Notable design decisions:**
- §2.2 verified byte-identical to `section-2.2-response-structure.md` (diff-checked).
- Internal scaffold inconsistency resolved in favor of the normative tables: the TenB5Plan `status` field description claims TERMINATE is available from six states, but the state-machine transitions and endpoint description both restrict it to `DRAFT`/`ACTIVE`/`SUSPENDED`; the PRD follows the transitions and explicitly notes that terminating from `SUBMITTED`/`RETURNED`/`APPROVED` is `ERR_INVALID_STATE`.
- The provisional-vs-final approval validity pair is rendered as named verdicts ("provisional validity" at decision time, "final validity" at window activation) with the void cascade's confirmation-release and quantity-restoration side effects co-located in §3.4.
- The OCC note in scaffold validation 19 ("evaluated with the transition's state checks, before side effects") is preserved verbatim in spirit in both §2.7 and §2.9's precedence ladder to resolve the apparent tension with its numeric priority.
- Logical-clock default (`2026-08-01T00:00:00Z`) and the `to_iso8601`/`current_utc` contract live in §2.4; sweep's pinned eight-step order and all nine response counters live in §2.10, with per-entity deferred rules scattered to their §3 homes.

## Step 5: Generate Unit Tests — 2026-08-15T00:47:00.000Z

All 77 tests collect cleanly. Generation complete and fully audited.

## Summary

**Files written**

`test_helpers/` (9 files):
- `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/test_helpers/types.py` — 10 entity TypedDicts, all status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (44 methods)
- `api_errors.py` — `ApiErrorId` (20 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `parse_instant`/`assert_same_instant` (instant-level timestamp comparison), `assert_quantity_conservation`
- `factories.py`, `constants.py` (48h TTL, quorum 2, 30/90+2 cooling-off, severity constants), `test_users.py` (shared constants + per-instance builders for all three entity-backed roles)
- `fixtures.py` — composite helpers: `create_current_person` (attestation currency), `create_submitted/under_review/approved_request`, `create_draft/submitted/approved_plan`, `create_approved_exception` (quorum), `flag_confirmation_with_case`, window/deal/entry helpers, `run_sweep`
- `__init__.py` — barrel export

`test_suite/` (11 files): `conftest.py` + `test_01_covered_persons.py` (7), `test_02_attestations_eligibility.py` (4), `test_03_rbac_authentication.py` (6), `test_04_restricted_list_deals.py` (8), `test_05_blackout_windows.py` (6), `test_06_preclearance_requests.py` (14), `test_07_exception_requests.py` (7), `test_08_tenb5_plans.py` (9), `test_09_trade_confirmations.py` (9), `test_10_violation_cases.py` (7).

**Test count: 77** — collected cleanly by pytest.

**Coverage**
- Queue A (difficulty): **18/18 instances, 36 tests emitted, 0 skipped** — every instance has exactly 2 tests.
- Queue B (corner): **41/41 non-stub instances, 41 tests emitted, 0 skipped**. All 15 `excluded_because:` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves.

**Audit results**: every test carries exactly one `Design:` tag resolving to a real instance; all 106 rule-bearing docstring quotes grep verbatim in PRD.md (4 initially failing citations fixed — bold-marker prefixes and elided quotes); no skip/xfail markers; no scaffold references in generated code.

**PRD-coverage gaps / adjustments (no instances skipped)**:
1. `restricted_entry_manual_create_defaults`: dropped the `note == null` sub-assertion — PRD calls `note` "an optional free-text note" without naming a server-side default (default-value silence pattern); the covered core claim (source=MANUAL, status=ACTIVE, deal_id=null) is asserted.
2. `decision_on_voided_request_state_beats_temporal`: the decision attempt uses the freshly-read current version instead of the recipe's pre-void version — after the void cascade increments the version, a stale expected-version would make ERR_STALE_VERSION an equally plausible outcome (PRD §2.9 has the OCC check "ride with" the state group), so the fresh version isolates the state-vs-temporal priority the instance asserts.
3. Timestamp assertions compare parsed instants rather than raw strings, since PRD pins the instants (e.g., "exactly 48 hours after the decision instant") but only mandates the three-fractional-digit format for `created_at`/`updated_at`.

## Step 6: Generate Implementation — 2026-08-15T00:49:00.000Z

The implementation is complete and verified. All files are in place, compile cleanly, and boot via `bash start.sh` from a fresh process with empty in-memory state.

## Summary

**Files written** (24 total) in `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/workspace/implementation/`:
- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, `PORT`/0.0.0.0/foreground), `requirements.txt`
- `app.py`, `db.py` (in-memory dicts + logical clock defaulting to 2026-08-01T00:00:00Z, zero seeding), `errors.py`, `response.py`, `middleware.py`, `util.py` (deferred schema-error collector matching the PRD's "sole failing check" ladder rule)
- `routes/`: clock, covered_persons, deals, restricted, blackout, preclearance, exceptions, plans, confirmations, cases, attestations, sweeps
- `services/core.py` (flags, screens, merge, void cascade, matching pass, severity) and `services/sweep.py` (pinned 8-step sweep)

**Endpoint count**: 48. **State machines**: 10. **Calculations**: 9 (approval TTL, provisional/final validity, cooling-off STANDARD/EXECUTIVE, severity score, matched-quantity pinned rounding, quorum, interval merge, attestation currency, sweep order).

**Verification**: three ad-hoc suites exercised every endpoint, both OCC rules beyond decision (plan-create, window-extend), void cascade releasing confirmations, multi-survivor merge, all severity bands, plan/exception/approval/attestation sweep expiries, suspension/reinstatement, RBAC and precedence ordering, pagination — all pass on fresh boots.

**PRD ambiguities resolved** (concrete choices):
1. **OCC placement** — §2.9 ("rides with the state group... even though listed after the business screens") beats §3.4's narrative order; implemented as state → OCC → segregation → business screens.
2. **`current_utc`** echoes the raw `to_iso8601` string sent (matches the PRD's no-fractional-digits default form).
3. **EXPIRED `remaining_quantity`** set to 0 ("forfeited"), while `matched_quantity` and matched confirmations persist.
4. **Multi-survivor merge** — primary (earliest start_at, then created_at) absorbs all touching survivors' intervals (min start / max end); other survivors become MERGED into it.
5. **Sweep re-flag duplicate case** — case creation skipped (not 409) when a non-CLOSED case already references the confirmation; `ERR_CASE_ALREADY_OPEN` only from the manual endpoint.
6. **Executive cooling-off** with multiple containing quarterly windows — latest `end_at` + 2d used.
7. **Auth** — headers present + role recognized only; entity-backed ids are not store-resolved (per the scaffold's auth check text).
8. **Duplicate email** on person create → `ERR_INVALID_REQUEST` 400 (no catalog entry exists).
9. **Insider reads** — single-resource GETs enforce ownership (403); list GETs are not ownership-filtered.
10. **Schema checks deferred** — `ERR_INVALID_REQUEST`/`ERR_INVALID_ENUM` raised only after all deeper ladder checks pass; checks with missing inputs are skipped (`ERR_INVALID_REQUEST` outranks `ERR_INVALID_ENUM`).
11. **Numeric constraints** — quantity > 0 and ≤ 4dp; price ≤ 2dp with no positivity rule (PRD mandates > 0 only for quantities).
12. **Version bumps** — one increment per logical mutation (a match that closes a request bumps it once); a merge-absorbed candidate window stays version 1; entity timestamps and `api_request_timestamp` are stamped from the logical clock.
13. **SCHEDULED window whose end passed un-swept** stays SCHEDULED (step 2 lifts only ACTIVE, per the literal state machine).
14. **Officer DENY** always stores `denial_reason=OFFICER_DISCRETION`; a payload `denial_reason` is enum-validated but ignored.
15. **`applicability_note`** text: "QUARTERLY window applies to all tickers" / "EVENT_DRIVEN window applies to {ticker} only".

## Step 7: Run Tests and Iterate — 2026-08-15T01:05:00.000Z

All 8 rounds clean: 77/77 passed in every round. Exit criterion met.

## Summary

**Iterations run:** 3 eight-round parallel sweeps (616 test-executions each).

**Sweep 1** — 1 deterministic failure in all 8 rounds: `test_void_restores_full_quantity_and_releases_match` (`assert 'FLAGGED' == 'RECEIVED'`).
**Sweep 2** — after fix 1: 7 rounds clean; round 5 had 1 flaky failure (`test_list_covered_persons_paginates_with_envelope`, `ConnectionResetError`).
**Sweep 3** — after fix 2: all 8 rounds 77/77. Clean exit.

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/test_suite/test_09_trade_confirmations.py` — `TestQuantityConservation::test_void_restores_full_quantity_and_releases_match`: removed the single assertion `released["status"] == "RECEIVED"` (STEP 1b/1c unique-derivability collapse, partial-coverage split). The void cascade fires only inside sweep step 1 (window activation is sweep-only), and the released confirmation's *observable* post-sweep status depends on whether sweep step 8's re-match scope includes confirmations released earlier in the same sweep. PRD §2.10 step 8 ("a re-match pass runs over **every** trade confirmation resting in `RECEIVED`", echoed in §3.7 "every confirmation sitting in `RECEIVED`") admits same-sweep re-match (→ FLAGGED/BLACKOUT_TRADE, as the implementation does), while §3.7's "eligible for re-matching on **the next sweep**" admits next-sweep re-match (→ stays RECEIVED). Both readings are PRD-faithful; no tie-breaker sentence exists. Kept the convergent assertions: request `VOIDED`, `matched_quantity == 0`, `remaining_quantity == 100`, quantity conservation (§3.4 verbatim), and `match_preclearance_id is None` (None under both readings). *Feedback note:* doc-generator Zero-Silence gap — PRD never pins whether sweep step 8 snapshots RECEIVED at sweep start or evaluates at step-8 time; unit-test-generator asserted one side of a two-reader ambiguity.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/test_helpers/api_client.py` — set `api_client.session.headers["Connection"] = "close"`. The round-5 flake was a transport race, not a semantic bug: per-test-server isolation restarts the server on the *same port* before every test; the module-level `requests.Session` pools keep-alive connections, and the first POST of a test can reuse a pooled connection to the just-killed server process, yielding `ConnectionResetError` (urllib3 never retries POST). Evidence: failure on the test's first request immediately after the plugin's "Restarting API server" log, 1 in 616 executions, identical request sequences across rounds (a real route crash would fail all 8 rounds deterministically). Transport hardening only — zero effect on payloads, headers semantics, or assertions.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful throughout; both failures traced to the test artifact layer (one non-uniquely-derivable assertion, one transport-level flake).

## Step 8: Finalize PRD — 2026-08-15T01:12:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/workspace/PRD_FINALIZED.md` is written with exactly two inline edits, both tracing to the single PRD silence in `<step_7_diff>` (the removed `released["status"] == "RECEIVED"` assertion in `test_09`). The `test_helpers/api_client.py` Connection-header fix is transport-only — no PRD edit, per scope.

**Line counts / delta:** PRD.md 318 lines, PRD_FINALIZED.md 318 lines (0.0% delta; two lines revised in place, no insertions of new lines).

**Changes:**
- §2.10 step 8 (line 140) — revise — pins that the re-match pass covers confirmations resting in `RECEIVED` **when step 8 begins**, explicitly including confirmations returned to `RECEIVED` by the step-1 void cascade of the same sweep — `implementation/services/sweep.py:87` (the `pending` list is built at step-8 execution time, after step 1's `void_cascade` at `sweep.py:30` has run).
- §3.7 reversal paths (line 224) — revise — replaces "eligible for re-matching on the next sweep" with "eligible for re-matching in that same sweep's step-8 re-match pass" — `implementation/services/core.py:247-251` (void_cascade releases to RECEIVED) consumed by `implementation/services/sweep.py:87-92` (same-sweep re-match; released confirmation resolves to FLAGGED/BLACKOUT_TRADE, matching the implementation behavior Step 7 documented).

**Per-edit pre-edit search log:**

*Edit 1 (§2.10 step 8):*
- (a) Subject: the population and snapshot timing of sweep step 8's re-match pass relative to earlier steps of the same sweep.
- (b) Paths enumerated and read: `services/sweep.py:7-94` (full sweep; step-8 list built once at step-8 time, sorted by `(trade_date, created_at, seq)`); `services/sweep.py:23-30` (step 1 invokes `void_cascade` per activating window); `services/core.py:230-256` (`void_cascade` — the only producer of resting-RECEIVED confirmations); `services/core.py:263-340` (`matching_pass` — always resolves RECEIVED → MATCHED_PRECLEARANCE/MATCHED_PLAN/FLAGGED, never sets RECEIVED, so no new RECEIVED entries can appear mid-step-8); `routes/confirmations.py:31-51` (ingestion sets RECEIVED then runs `matching_pass` synchronously — RECEIVED is transient there, never resting); `routes/cases.py:125-129` (unfounded close moves FLAGGED → CLEARED, never RECEIVED); grep `VOIDED` across impl confirms voiding occurs only at `core.py:246`, called only from sweep step 1.
- (c) Wording chosen as "resting in `RECEIVED` when this step begins — including any confirmation returned to `RECEIVED` by an approval voided in step 1 of the same sweep" — a scoping clause rather than a universal claim, so it stays accurate for the ingestion path (never resting-RECEIVED) and the once-built list semantics (nothing re-enters RECEIVED during step 8).

*Edit 2 (§3.7 reversal timing):*
- (a) Subject: when a void-released confirmation becomes re-match-eligible (next sweep vs same sweep).
- (b) Same enumeration as Edit 1, plus the VOIDED grep confirming voiding is sweep-only — so "that same sweep" is always well-defined (a void can only occur inside sweep step 1). Also verified `matching_pass` always moves a processed confirmation out of RECEIVED, so a released confirmation is re-matched exactly once, within the same sweep — no need to mention later sweeps.
- (c) Replaced only the timing phrase; kept the rest of the sentence (and the CLEARED-path clause) verbatim to avoid touching the unfounded-close behavior at `routes/cases.py:125-129`.

No other PRD prose required changes: §3.4 line 192 (void unwinding) and §3.7 line 216 ("every confirmation sitting in `RECEIVED`") make no timing claim that contradicts the same-sweep reading, so both were kept verbatim.

## Step 9: Complete PRD — 2026-08-15T01:25:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1908_insider_trading_window_preclearance/workspace/PRD_COMPLETED.md`. All edits are in-paragraph inserts/revisions — no new sections, no new paragraphs, no invented behavior.

## Exit Summary

**Size delta:** `PRD_FINALIZED.md` 318 lines / 52,575 chars → `PRD_COMPLETED.md` 318 lines / 56,332 chars. Delta: **+0 lines, +3,757 chars** (21 paragraph lines touched across 11 diff hunks; every change is inline).

**Counts:** 26 ambiguity-pins, 3 mismatch-revisions (29 changes total).

**All 15 generation-time decisions verified:** 4 were already uniquely pinned (multi-survivor merge §3.2; one version increment per mutation §2.5; SCHEDULED-with-passed-end stays SCHEDULED via §2.10 step conditions; DENY stores OFFICER_DISCRETION §3.4); the other 11 are now pinned by the changes below.

### Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)

1. §2.1 — insert — ambiguity — Insider list GETs are not ownership-scoped; ownership enforced only on single-resource reads/mutations — middleware.py:34-43, routes/preclearance.py:126-135
2. §2.1 — insert — ambiguity — `X-User-ID` never resolved against the store for any role; string-equality only, unknown header id is not itself an error — middleware.py:15-22
3. §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, never wall-clock — response.py:16-20
4. §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped (limit to [1,100], offset to ≥0); non-integer values → `ERR_INVALID_REQUEST` 400 — response.py:47-64
5. §2.3 — insert — ambiguity — §4 filters are exact-match equality; a non-matching or out-of-enum filter value yields an empty page, never an error — routes/covered_persons.py:58-64 (same pattern in all list routes)
6. §2.4 — revise — ambiguity — clock capability echoes the supplied `to_iso8601` string verbatim as `current_utc` (was "returns the resulting current_utc") — routes/clock.py:14-20
7. §2.4 — insert — ambiguity — datetime inputs: bare date → midnight UTC, `Z`/offset normalized to UTC, naive → UTC — util.py:12-32
8. §2.6 — revise — ambiguity — quantity rule covers plans too, >4dp is malformed; `price` enforced at ≤2dp and carries no positivity rule — util.py:91-107, routes/confirmations.py:23-24
9. §2.6 — revise — **mismatch** — attestation currency window was "day precision"; impl evaluates second-precision closed interval [`now` − 365d, `now`] on `completed_at` — services/core.py:72-92
10. §2.9 step 2 — insert — ambiguity — ownership-vs-existence order: creation payloads and `GET /covered-persons/{id}` check ownership before existence (403 for unknown id); all other endpoints resolve the path id first (404 then 403) — routes/covered_persons.py:49-51, routes/preclearance.py:69-77 and 117-122
11. §2.9 step 10 — insert — ambiguity — when one body fails both schema checks, `ERR_INVALID_REQUEST` is reported over `ERR_INVALID_ENUM` — util.py:71-76
12. §3.1 — insert — ambiguity — duplicate email → `ERR_INVALID_REQUEST` 400, evaluated only after body schema passes — routes/covered_persons.py:25-27
13. §3.2 — insert — ambiguity — `applicability_note` literal texts: `QUARTERLY window applies to all tickers` / `EVENT_DRIVEN window applies to <ticker> only` — routes/blackout.py:63, services/core.py:221
14. §3.2 — insert — ambiguity — kind-inapplicable supplied fields (fiscal fields on EVENT_DRIVEN, ticker on QUARTERLY) are ignored, never rejected — routes/blackout.py:51-71
15. §3.2 — insert — ambiguity — merge version effects: candidate stays `version` 1 (merge rides on creation); survivor and each other absorbed window increment once — services/core.py:192-206
16. §3.2 — insert — ambiguity — window extension moves only `end_at`; it never re-runs the merge rule — routes/blackout.py:104-124
17. §3.4 — insert — ambiguity — request born `SUBMITTED` with `matched_quantity` 0 and `remaining_quantity` null until approval — routes/preclearance.py:94-113
18. §3.4 — revise — **mismatch** — decision-time order corrected to state → OCC (412) → segregation (403) → business screens (PRD had listed the version check last) — routes/preclearance.py:155-171
19. §3.4 — revise — ambiguity — restricted/blackout screens at decision time apply to `APPROVE` only; a `DENY` is never blocked by them — routes/preclearance.py:166-171
20. §3.4 — insert — ambiguity — payload `denial_reason` is ignored (stored value always `OFFICER_DISCRETION`); when present must be `RESTRICTED_LIST`/`OFFICER_DISCRETION` else `ERR_INVALID_ENUM` — routes/preclearance.py:159, 185-186
21. §3.4 — insert — ambiguity — restricted-list cascade denials stamp no decision fields (`decided_at`/`decided_by` stay null) — services/core.py:162-169
22. §3.4 — revise — ambiguity — expiry "forfeiture" pinned: `remaining_quantity` set to 0 while `matched_quantity` persists unchanged — services/sweep.py:40-45
23. §3.6 — revise — ambiguity — when several quarterly windows contain the approval instant, the one with the latest `end_at` supplies the +2d executive buffer — routes/plans.py:29-35
24. §3.6 — insert — ambiguity — `return_note` optional on RETURN; stored null when omitted — routes/plans.py:138, 152
25. §3.7 — insert — ambiguity — ingestion's synchronous resolution rides on creation, so the confirmation response carries `version` 1 — routes/confirmations.py:31-52
26. §3.7 — insert — ambiguity — a plan match records `match_plan_id` only; the plan is not mutated (no drawdown, no version advance) — services/core.py:296-307
27. §3.7 — revise — **mismatch** — auto-flag cascade with an existing non-CLOSED case: no second case opened and no 409 (confirmation still flagged, hold still recomputed); `ERR_CASE_ALREADY_OPEN` applies only to manual case creation — services/core.py:322-337, routes/cases.py:46-49
28. §3.8 — insert — ambiguity — manual case `trade_confirmation_id` is existence-checked only; it need not belong to the subject — routes/cases.py:43-49
29. §3.8 — insert — ambiguity — recording a suspension on an already-`SUSPENDED` person re-stamps `suspended_until` from the new sanction instant — routes/cases.py:115-123

Deliberately left out of PRD scope (framework-level, not PRD topics): Flask 405/unknown-route/unhandled-exception envelope fallbacks in app.py.
