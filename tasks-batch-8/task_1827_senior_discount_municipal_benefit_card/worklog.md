# Worklog — task_1827_senior_discount_municipal_benefit_card

## Step 1: Create Task Directory — 2026-08-14T19:08:00.000Z

Pre-created by pipeline launcher: `tasks/task_1827_senior_discount_municipal_benefit_card/` and `workspace/` already exist (verified via ls). Skipped per invocation args.

## Step 2: Generate Scaffold — 2026-08-14T20:09:00.000Z

All three scaffold artifacts are generated and lint-clean. Summary:

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/`:

- **SCAFFOLD.yaml** (§1.0–§1.7 only) — 10 entities, 34 endpoints, 42 error codes, 9 ordered validation priorities, 8 calculation rules, 8 state machines, 1 OCC concurrency rule, 6 roles
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single `scaffold_difficulty_design:` key, 18 instances (2 per each of the 9 Difficulty Rules), all with fully structured `setup_api_calls`/`trigger`/`assert` chains and hand-computed numeric literals
- **SCAFFOLD_CORNER_DESIGN.yaml** — single `scaffold_corner_design:` key, 68 instances across all 9 claim-extraction-guide sections (54 real test recipes + 14 `excluded_because:` stubs citing §1.8 instances)

## Design highlights

- **Complexity profile**: compliance/audit primary + quota/allocation secondary; flat FK topology; cyclic state machines; **segregation-of-duties** role model (application approver ≠ document reviewer; flag clearer ≠ flag raiser); layers: optimistic concurrency, scheduled actions (logical clock, default `2026-08-01T00:00:00Z`), derived-field reconciliation, rate thresholds
- **Difficulty mechanics**: provisional-vs-final claim amounts diverging over a FLAGGED transaction (2500 vs 2000); calendar-day vs trailing-24h velocity windows producing different outcomes for identical history; nested-min discount chain (raw 500 / cap 700 / monthly remaining 100 → 100); pinned per-line-then-sum rounding (153 ≠ 152); depth-4 fraud cascades in both directions (flag → count → suspend → cards, and the clear-flag unwind); state-vs-fiscal and referential-vs-safety validation priority conflicts; half-open offer windows vs closed waiver intervals; age-65 and merchant-cap exact boundaries; card-count and ytd-total compensating invariants
- **Reachability**: every state is reachable via declared endpoints; the single test-driving endpoint `POST /senior-benefits/_clock/set_current_utc` (with pinned startup default) drives all time-based transitions (recert window, lapse, card expiry, offer retirement)

## Verification

- `scaffold_lint.py`: **VERDICT: clean lint** — 906 calls scanned, all §1.8/§1.9 calls conform to §1.5, all FKs reverse-reachable
- Zero unbound `${var}` placeholders; OCC `expected_cardholder_version` always references a captured version; negative tests use the error-envelope capture convention
- No forbidden concurrency vocabulary; all 42 error codes referenced by at least one design instance; instance names unique across both design files; scenario string stored verbatim

Note: the pre-existing `worklog.md` and `workspace/` in the task directory were left untouched.

## Step 3: Copy Shared Files — 2026-08-14T20:10:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1827_senior_discount_municipal_benefit_card/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T20:21:00.000Z

The PRD has been generated at `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/workspace/PRD.md`. The withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

**Document structure:**
- **§1** — 2-paragraph introduction from the program-goals angle (compliance environment + finite funding pools), with the `/senior-benefits` mount noted.
- **§2** — 10 subsections: RBAC with per-role identity binding (Cardholder/MerchantOperator entity-backed; Applicant/EligibilitySpecialist/ProgramAdministrator/FraudAnalyst opaque), the verbatim §2.2 envelope block, pagination (limit 10/1/100, offset 0, `created_at` ascending), the logical clock (startup 2026-08-01T00:00:00Z, dependency-ordered time transitions), common resource properties, integer-cents/half-up precision, OCC (`expected_cardholder_version` → `ERR_STALE_VERSION` 412, card-issuance endpoint only), left-to-right nested retrieval (8-member 404 family; no `ERR_OFFER_NOT_FOUND` invented), ownership boundaries, and the pinned 9-tier validation evaluation order.
- **§3** — 8 subsections organized by business lifecycle: application/eligibility gates (65 years, $24,000 income limit), document review, approval/enrollment/recertification cycle, card replacement/renewal, merchants/offers/fee waivers, purchase recording (offer selector, discount min-chain with single terminal rounding, velocity windows 10-per-24h reject then 5-per-day auto-flag), fraud flag/clear/void with threshold-3 suspension cascades, and reimbursement claims against the fund (per-line-then-sum pinned rounding, provisional vs. final bases).
- **§4** — 34-endpoint table, 4 columns only.
- **§5** — 42-error catalogue, 2 columns only.

**Hard contract reports:**

```
Field coverage check:
- entities[].fields: 48 required, 48 present, 0 missing
- endpoints[].request_body/input (incl. to_iso8601, expected_cardholder_version, decision, reason): 24 required, 24 present, 0 missing
- endpoints[].query_params (limit, offset, status, category, waiver_type, card_id, cardholder_id, merchant_id, offer_id): 9 required, 9 present, 0 missing
- path params (id, docId): 2 required, 2 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 9 tiers checked, 9 expressed in prose (§2.10 global order; pinned per-endpoint orders at approval §3.3, document review §3.2, purchase recording §3.6), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (write endpoint named in §2.7 + expected_cardholder_version + ERR_STALE_VERSION/412 in §2.7 and §3.4), 0 missing
- state_machines[].transitions: 27 checked (BenefitApplication 5, VerificationDocument 2, Cardholder 10, BenefitCard 7, DiscountOffer 1, UsageTransaction 3, ReimbursementClaim 2, Merchant 1 — incl. all sibling from-state branches), 27 fully expressed, 0 missing
- calculations[]: 8 checked (age, income, discount_amount, merchant_claim_amount with both basis variants and pinned round-then-sum order, velocity both windows with enforcement order, ytd totals, fund_available invariant, offer_selector with defensive tie-break), 8 fully expressed, 0 missing
- validations[] conditions: 42 error IDs all matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 34 checked, 34 expressed (incl. ownership applies_to set enumerated in §2.9, ERR_CARDHOLDER_NOT_ACTIVE covering usage/issuance/fee-waiver), 0 missing
- entities[].fields[] structured content: null-until defaults, computed-field inclusion sets, and enum memberships all reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (revoke from 4 states, expiry from ACTIVE/SUSPENDED, suspension restore to either pre-suspension status, replacement vs. renewal, provisional vs. final claim basis, velocity windows), all with equal density
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 395
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. No fuzzy/approximating wording or operator pseudocode appears outside the fixed §2.2 block; numeric constants use unit conversion ($24,000/year income limit, $50/month discount ceiling) with explicit boundary inclusivity.

## Step 5: Generate Unit Tests — 2026-08-14T20:57:00.000Z

Done. Generated complete test infrastructure for task_1827 (Senior Discount & Municipal Benefit Card Program).

## What was generated

**`test_helpers/` (Stage 1)** — 9 files:
- `types.py` — 10 entity TypedDicts + 13 status/role enums (all entities carry the full common-fields set)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (34 methods, `/senior-benefits` prefix)
- `api_errors.py` — all 42 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_fund_invariant` (allocated == available + paid)
- `factories.py`, `constants.py` (velocity 5/10, fraud threshold 3, income limit 2400000, monthly cap 5000, default clock)
- `test_users.py` — 6 roles; per-instance builders for the entity-backed roles (`make_cardholder_headers`, `make_merchant_operator_headers`), which all ownership-gated fixture calls use
- `fixtures.py` — composite chains: `onboard_cardholder` (9-call enrollment), `submit_and_approve_recertification`, `setup_merchant_with_offer`, `setup_posted_transactions`, `setup_suspended_cardholder` (flag-cascade terminal state), `setup_submitted_claim`, `file_claim`, `set_clock`
- `__init__.py` — barrel export of framework generics + PRD-specific names

**`test_suite/` (Stage 2)** — `conftest.py` + 8 domain-organized test files, **91 tests**.

## Design-index contract verification (all automated checks green)

- **Queue A**: all 18 difficulty instances have ≥2 tests each (36 tests)
- **Queue B**: all 54 non-stub corner instances have ≥1 test each; all 14 `excluded_because` stubs untranslated with pointers verified to resolve
- Every test docstring ends with exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` tag; zero unresolved tags
- **Citation audit**: every `PRD §x.y` quote extracted from all 91 docstrings greps verbatim against PRD.md (0 misses), including the inner-quoted envelope sentences
- `pytest --collect-only` collects 91 tests; pyflakes clean; no `skip`/`skipif`/`xfail`; no scaffold references in comments

## Notable adjudications (PRD-first filter)

- **`version == 1` at creation is NOT asserted** — this task's PRD §2.5 says only "increments with every modification" (unlike e.g. task_1500's PRD which pinned "starts at 1"), so creation tests assert the derivable core (status, null workflow fields, server-minted UUID) plus `isinstance(version, int)`. Relative version rules that the PRD does pin ("every successful issuance increments the cardholder's `version` by one", §3.4) are asserted exactly in the OCC and replacement tests.
- **`system_fields_client_input_ignored`** kept: honoring a non-UUID client `id` would violate §2.5's UUID guarantee, so "server-minted id wins" is uniquely derivable; `version != 99` follows from "system-managed".
- **`immediate_consistency_read_after_write`** kept on the strength of §3.6's verbatim "frozen on the transaction as `discount_cents`, immutable thereafter" + §2.2's return-the-resource rule.
- Priority-pair tests (state-vs-fiscal on claim approval, ownership-vs-velocity on usage) are backed by §2.10's explicit pinned-order prose plus §3.6/§3.8 endpoint-level ordering sentences, so they survive the two-reader test.

Numeric fixtures were translated verbatim from the pre-audited recipes (e.g. provisional 2500 vs final 2000 divergence; round-per-line 153 vs 152; cap 1000-pass/1001-fail; velocity calendar-day vs trailing-24h divergence at counts 1/5 and 6/10).

## Step 6: Generate Implementation — 2026-08-14T20:44:00.000Z

Complete. I generated a full Python + Flask implementation for task 1827 at `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/workspace/implementation/`, derived solely from the PRD and scaffold (grading artifacts were not read).

**Files produced**
- `start.sh` — executable; guards `pip install` behind `python3 -c "import flask"` so per-test-server reboots are no-ops; `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000).
- `app.py` — entry point, envelope-compliant error handlers, blueprints mounted under `/senior-benefits`.
- `clock.py` — logical clock, starts at exactly `2026-08-01T00:00:00Z`, never wall-clock.
- `store.py` — empty in-memory dicts; zero seeding at boot.
- `errors.py` — all 39 error IDs with the scaffold's exact HTTP statuses.
- `util.py` — response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, clamped to [1,100]), ISO-8601 3-fractional-digit timestamps, field validators, `version` starting at 1 with `bump()` on every mutation.
- `auth.py` — `X-User-ID`/`X-User-Role` auth, the six roles, entity-backed identity resolution for `Cardholder`/`MerchantOperator` (unknown entity → 401), role authorization, ownership helpers.
- `services.py` — derived fields (age_years, fraud_flag_count, ytd totals, current-month reimbursed), offer selector (half-open window, earliest valid_from tiebreak), discount calc (exact rational → per-txn cap → $50 monthly headroom → single round-half-up), claim calc (per-line round-half-up then sum, provisional POSTED+FLAGGED vs final POSTED-only), velocity counts (trailing-24h reject ≥10, calendar-day auto-flag ≥5), fraud suspension/restoration cascades, clock-driven transitions in dependency order (recert window → lapse + card-expiry cascade → card expiry → offer retirement), 16-digit card minting.
- `routes/` — all 30 endpoints across `clock_routes`, `applications` (+documents), `cardholders` (+cards OCC issuance, revoke, fee-waivers), `merchants` (+offers), `usage` (transactions/void/flag/clear-flag), `funding` (program funds, reimbursement claims).

**Key fidelity points implemented**
- Pinned validation ordering per PRD §2.10: auth → role → left-to-right path existence (doc-under-wrong-app → `ERR_DOCUMENT_NOT_FOUND`) → state → ownership → velocity/segregation → temporal → uniqueness/eligibility → fiscal; usage creation's standing checks in the pinned card → cardholder → merchant order; approve's four-check order (state → segregation → document completeness → recert timing).
- OCC on `POST /cardholders/{id}/cards` via `expected_cardholder_version` → 412; issuance bumps cardholder version exactly once; REPLACEMENT supersedes live card, RENEWAL links most-recent EXPIRED card without touching expired statuses.
- Segregation of duties on approval (approver ≠ intake reviewer and ≠ any VERIFIED document's reviewer) and on clear-flag (manual flagger cannot clear; `SYSTEM` flags clearable by any analyst).
- Velocity hard-reject (422) before persistence, calendar-day persist-then-auto-flag with the full suspension cascade; suspension preserves `pre_suspension_status` and restores it when flags drop below 3.
- Recertification cycle: window opens at due−60d, lapse at due+1d with card-expiry cascade, approval restores ACTIVE + refreshes income/address + due=+365d, lapsed cards stay EXPIRED.
- Claims: duplicate-pending rule, period strictly before current month, fund binding by period year, 402 insufficiency, merchant monthly cap, termination cascade (`MERCHANT_TERMINATED` denial), fund paid/available invariant with fund version bump on debit.

**Verification**: booted via `bash start.sh` from a fresh process and ran a 107-check end-to-end smoke script covering every entity, state machine, calculation (including the round-per-line claim basis and the flagged-between-filing-and-approval final<provisional case), ownership boundaries, eligibility boundaries (age exactly 65, income exactly 2400000), adjacency rules for both window types, velocity across two calendar days, and the clock-transition dependency order — all passing, with a second consecutive fresh boot confirming clean restartability.

## Step 7: Run Tests and Iterate — 2026-08-14T21:20:00.000Z

**Summary**

- **Iterations run:** 2 eight-round parallel sweeps (16 total rounds).
  - Sweep 1: rounds passed 91/91 in 3/8 rounds; `test_trailing_24h_window_governs_hard_reject` failed in 5/8 rounds (all at the same wall-clock second — a host load spike), each time with `requests.exceptions.ConnectionError` ("Remote end closed connection without response" / "Connection reset by peer").
  - Sweep 2 (post-fix): all 8 rounds 91/91, zero failed/error/skipped. Exit condition met.

- **Root cause (transport flake, not a PRD rule):** the failure tripped on the *first request of the test* (`POST /senior-benefits/applications` inside `onboard_cardholder`), immediately after the runner's per-test-server SIGKILL-and-respawn. The module-level `ApiClient` holds a `requests.Session` whose urllib3 keep-alive pool can hand back a connection opened against the just-killed server instance; under load spikes the dead instance's FIN/RST interleaves with the pool's `is_connection_dropped` checkout check, and the request dies mid-flight. Server logs showed zero tracebacks; the implementation was never at fault. No PRD rule was implicated, so no test deletion was warranted.

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** `api_client.py` — added `ApiClient.__init__` that sets `self.session.headers["Connection"] = "close"`, so every request opens a fresh TCP connection and can never ride a connection that predates the current server instance. Transport hygiene only; no assertion, fixture, or payload semantics changed. Smoke-verified (201 create + 30 sequential GETs) before the rerun.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** none — the implementation was already fully PRD-faithful and passed every assertion in every round.

Key file: `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/test_helpers/api_client.py`

## Step 8: Finalize PRD — 2026-08-14T21:27:00.000Z

Done. PRD_FINALIZED.md is written and byte-identical to PRD.md — the correct minimal patch for this step_7_diff is the empty patch.

## Summary

**Line counts / %-delta**
- `PRD.md`: 284 lines
- `PRD_FINALIZED.md`: 284 lines
- Delta: 0 lines, 0.0% — zero edits.

**Changes (one bullet per change)**
- None. The step_7_diff contains no item that traces to a PRD silence or PRD/impl mismatch.

**Per-diff-item traceability analysis (the mandatory (a) subject / (b) impl-path enumeration for each step_7_diff item, with the resulting no-edit decision)**

1. **Flaky test `test_trailing_24h_window_governs_hard_reject` (5/8 sweep-1 rounds, ConnectionError)**
   - (a) Subject: trailing-24h velocity hard-reject rule and the transport flake that tripped before it.
   - (b) Impl paths enumerated: `/home/ubuntu/.../implementation/services.py:118-131` (`velocity_counts`: `window_start < created_at <= now`, VOIDED excluded, candidate counted, threshold `TRAILING_24H_REJECT_THRESHOLD = 10` at line 17); the failing test at `test_suite/test_05_usage_discounts_and_velocity.py:259-287`; the Step 7 failure signature (`requests.exceptions.ConnectionError` on the first request inside `_setup_velocity_divergence`/`onboard_cardholder`, before any velocity assertion). The impl matches PRD §3.6 verbatim — the test's own docstring quotes the PRD sentence and the code implements exactly that window semantics. The failure was a keep-alive connection reused across the runner's SIGKILL-and-respawn, not a behavioral divergence.
   - (c) Decision: no edit — PRD already uniquely determines the rule; the flake never implicated it.

2. **test_helpers/api_client.py fix (`Connection: close` header in `ApiClient.__init__`)**
   - (a) Subject: HTTP client transport hygiene for per-test-server isolation.
   - (b) Impl paths enumerated: `test_helpers/api_client.py:8-20` (the added header, with its own comment stating "No assertion or fixture semantics change — this is transport hygiene only"); the server side (`implementation/app.py`, `routes/*.py`) has no behavior conditioned on the `Connection` header; all 8 `results.N.json` files post-fix show 91/91 passed, 0 failed/errors/skipped.
   - (c) Decision: no edit — this is a pure fixture bug, the canonical case the method excludes. The PRD governs the API's behavioral contract; pinning a client-side TCP connection-reuse requirement would invent behavior the server neither exhibits nor enforces, violating the "never invent behavior" rule.

3. **Implementation fixes / test deletions / test_suite fixes** — the diff lists none, and file mtimes corroborate it: all `implementation/` source files are stamped 20:31–20:37, before the 21:02+ test-run artifacts (`__pycache__`, `results.*.json`). Nothing to trace, nothing to patch.

**Artifact**: `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/workspace/PRD_FINALIZED.md` (verified byte-identical to `PRD.md` via `cmp`).

## Step 9: Complete PRD — 2026-08-14T21:33:00.000Z

Status codes align with PRD §4 (creates → 201, modifications/reads → 200). All endpoints and guard orders are covered. The task is complete.

## Summary

**Source vs. output:** `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/workspace/PRD_FINALIZED.md` (284 lines, 47,167 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1827_senior_discount_municipal_benefit_card/workspace/PRD_COMPLETED.md` (286 lines, 50,266 chars; +2 lines, +3,099 chars).

**Counts:** 11 ambiguity-pins, 1 mismatch-revision (12 total edits across 10 edit sites).

**Change log:**
- §2.2 (error format) — insert — ambiguity — pinned the three fallback errors `ERR_NOT_FOUND` (404, unmatched route), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500) — implementation/app.py:39-51.
- §2.3 (pagination) — revise — ambiguity — pinned that non-integer `limit`/`offset` is `ERR_INVALID_REQUEST` while out-of-range integers are clamped (limit into [1,100], offset floored at 0), `created_at` ties break by insertion order, and enum filter query params are validated with `ERR_INVALID_REQUEST` on unrecognized values — implementation/util.py:130-164.
- §2.4 (logical clock) — revise — ambiguity — pinned that the clock response `data.current_utc` echoes the supplied `to_iso8601` string verbatim, offset-less values are interpreted as UTC, and unparseable values yield `ERR_INVALID_REQUEST` — implementation/routes/clock_routes.py:12-23, implementation/clock.py:18-22.
- §2.9 (ownership boundaries) — revise — ambiguity — pinned that the usage-transaction list is auto-scoped for entity-backed callers even with no filter supplied, and that reading a single transaction belonging to another party yields the corresponding ownership-mismatch error — implementation/routes/usage.py:121-157.
- §3.1 (application submission) — insert — ambiguity — pinned the fixed check order: payload shape → RECERTIFICATION cardholder existence (404) and Cardholder-self ownership (403) → age gate → income gate → duplicate-pending/recert-timing; also pinned that an `Applicant`-role caller may submit a recertification naming any existing cardholder — implementation/routes/applications.py:46-86.
- §3.2 (document attach) — insert — ambiguity — pinned that attachment is open: no application-state restriction and no cardholder-ownership check on attach — implementation/routes/applications.py:221-239.
- §3.2 (document review) — insert — ambiguity — pinned that a `rejection_reason` supplied with a `VERIFIED` decision is ignored and stored empty — implementation/routes/applications.py:266-272.
- §3.3 (revocation) — revise — mismatch — PRD said revocation requires "supplying a `reason`"; impl accepts but neither requires nor persists it, and clears `pre_suspension_status`; revised to match — implementation/routes/cardholders.py:116-130.
- §3.4 (REPLACEMENT) — insert — ambiguity — pinned that with several live cards the most recently created one is superseded and others keep status — implementation/routes/cardholders.py:86-93.
- §3.6 (record purchase) — revise — ambiguity — pinned body-identifier resolution order (card 404 before merchant 404) and that the ownership check fires after the three standing checks and before velocity control — implementation/routes/usage.py:55-73.
- §3.7 (void) — insert — ambiguity — pinned that voiding checks only transaction status and caller ownership, not merchant `ACTIVE` status, so a terminated merchant's operator may still void their POSTED transactions — implementation/routes/usage.py:160-174.
- §3.8 (program fund) — revise — ambiguity — pinned `fiscal_year` as an integer field — implementation/routes/funding.py:48.

Everything else in implementation/ (state machines, cascades, discount and claim calculation chains, velocity thresholds and window semantics, OCC gate, segregation-of-duties guards, approval check order, envelope shape, 201/200 status mapping, serializer field sets) was already uniquely pinned by the PRD and required no change. `ERR_OFFER_NOT_FOUND` is defined in implementation/errors.py:23 but never raised by any endpoint, so no catalogue entry was added.
