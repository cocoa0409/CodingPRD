# Worklog — task_0977_asl_cart_deaf_interpreting

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0977_asl_cart_deaf_interpreting` with `workspace/` subdirectory already existed; no auto-index scan run per instructions. Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-10T09:07:00.000Z

All three scaffold artifacts generated for task 0977 (ASL/CART Deaf-Interpreting & Scheduling), written to `/home/ubuntu/github/CodingPRD/tasks/task_0977_asl_cart_deaf_interpreting/`, lint-clean, calibrated beyond Expert level.

## Files written

- **SCAFFOLD.yaml** — §1.0–§1.7 only (no design keys). Fixed response envelope verbatim; logical-clock endpoint with mandated default `2026-05-01T00:00:00Z`.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top key `scaffold_difficulty_design:`.
- **SCAFFOLD_CORNER_DESIGN.yaml** — single top key `scaffold_corner_design:`.

## Counts

| Element | Count |
|---|---|
| Entities | 13 (RequestingOrg, RateCard, Interpreter, Certification, AvailabilityWindow, InterpretingRequest, Assignment, Encounter, Invoice, Complaint, CreditMemo, StrikeRecord, ReportingSnapshot) |
| Endpoints | 67 (incl. `POST /_clock/set_current_utc` with 3 ordered deferred sweeps) |
| Error codes | 55 |
| State machines | 8 (request re-match cycle with counter exit; invoice parallel payment×dispute dimensions; suspension/reinstate cycle; complaint reopen-once cycle) |
| Calculations | 14 (provisional vs final billing, per-line-then-sum rounding, nested-min travel caps, tiered cancellation fee with inclusive boundaries, rolling 365-day strike threshold, dual-variant quality scores, oldest-first credit waterfall, aggregate VRI capacity, buffered double-booking) |
| Validations | 12 priorities (auth → schema → role → ownership → existence → OCC(412) → posture → from-state → ADA safety → temporal → constraint → fiscal) |
| Concurrency rules | 2 OCC (offer supersede on request version; credit memo on org version) |
| Roles | 6, segregation-of-duties model; entity-backed OrgRequester/Interpreter |

## Difficulty design coverage (§1.8): 18 instances, 2 per rule

- **dual_variant_calc**: billing estimate 26200 vs final 24840 (Invoice domain); quality score 85 vs provisional 55 (Interpreter domain)
- **combinatorial_formula**: mode (b) per-line-then-sum rounding (24681 vs 24680 one-cent split); mode (a) nested-min travel/mileage caps (45500)
- **non_linear_state_machine**: request offer-decline cycle → UNFILLED at 3 attempts; invoice (PARTIALLY_PAID × OPEN) parallel dimensions
- **transitive_cascade**: depth-5 no-show → strike → suspension → assignment cancel → request re-match; depth-4 substantiation → credit memo → waterfall → invoice PAID → request CLOSED
- **priority_pair_validation_conflict**: state vs business_temporal (check-in); business_safety vs business_fiscal (offer)
- **boundary_precision_check**: exactly-48h cancel → fee 0 (hours, cancel endpoint); 2→3 strike suspension (count, mark-no-show endpoint)
- **cross_entity_state_dependency**: Org→Request submit gate; Encounter→Request/Invoice verification gate
- **resource_temporal_overlap**: half-open adjacency on AvailabilityWindow vs aggregate capacity-3 on VRI sessions
- **compensating_invariant**: credit apply/void money conservation (amount_due == subtotal − credits − payments); strike create/rescind count conservation with no auto-reinstate

All numeric assertions pre-computed as literals; every `${var}` traceable to an earlier `captures:`; OCC version fields always placeholder-bound.

## Corner design coverage (§1.9): 70 instances (59 active + 11 stubs)

All nine guide sections: entities (7), state_machines (5: terminal lockdown, invalid transitions, side-effect execution, conditional cascade, reopen-once cycle), calculations (6 active + 3 stubs: minimum-minute floor, VRI platform-fee-on-actual-minutes trap, 365-day inclusive strike boundary, VRI estimate constants, 24h partial-tier fee, partial waterfall oldest-first, half-open report window), validations (8: auth, priority ordering, lead-time, conditional address, coverage gap merge, buffer reject/allow, credit-limit equality, quality gate, overpayment), cross_cutting_layers (7 active + 3 stubs: OCC×3, three clock sweeps with boundary assertions, pagination+filter), endpoints (6 active + 2 stubs: rate-pinning surviving card retirement, supersede, overturned adjustment line, void reversal, corrected times, platform-wide report), errors (12 active + 2 stubs covering every previously untriggered catalog code), rbac (6: ownership denials, SoD both directions, peer isolation, shared reads), consistency_model (1 stub).

## Verification

`scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1307 calls scanned, 18 FKs reverse-reachable). A supplementary audit confirmed: 88 unique instance names across both files, zero unbound placeholders, all grounds resolve, all stubs cite existing difficulty instances, no forbidden concurrency vocabulary, enum closure holds (every status value has a producing transition). No sibling task directories were read; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-10T09:08:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_0977_asl_cart_deaf_interpreting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T09:15:00.000Z

All contracts pass. The PRD was written to `/home/ubuntu/github/CodingPRD/tasks/task_0977_asl_cart_deaf_interpreting/workspace/PRD.md`.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_0977_asl_cart_deaf_interpreting/workspace/PRD.md` — 343 lines, ends at §5 with no audit footer.

**Section list:**
- §1 Introduction (3 paragraphs: ADA business context, role segregation/system scope, logical-clock determinism)
- §2 Global Specifications — 2.1 RBAC (all 6 roles with identity translations), 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 The Logical Clock and Deferred Sweeps, 2.5 Common Resource Properties (incl. StrikeRecord's absent `updated_at`/`version`), 2.6 Money/Precision/Round-Per-Line, 2.7 Optimistic Concurrency Control (both OCC rules with 412 error IDs), 2.8 Nested Resource Retrieval (all 13 not-found IDs), 2.9 Hierarchical Consistency (bubble-ups/cascades), 2.10 Validation Priority Order (all 12 tiers incl. the 9th-tier ADA sub-order)
- §3 Business Logic — 9 subsections: orgs/fiscal posture; interpreter onboarding/credentialing/availability; request submission/scheduling; rate-card selection/offer dispatch/pinned snapshot; assignment progression; cancellation/no-show/strike cascade (4-link); encounter verification/invoice composition; settlement/disputes/credit waterfall; complaints/adjudication/quality scoring/reporting
- §4 Endpoint Definitions — 4-column table, 67 rows (matches scaffold count)
- §5 Error Code Catalogue — 2-column table, 55 rows

**Contract reports:**
- Contract 1 (Field-Name Coverage): entities[].fields 116/116, endpoint I/O names 17/17, query params 13/13, path params 3/3 — **PASS**
- Contract 2 (Rule Coverage): spot audit over all 14 calculations (constants 40/365/3/200mi/240min/30min/15min/72h/24h/2h, penalties 5/15/30, credit defaults, VRI capacity 3, round-per-line, credential mapping, waterfall ordering, OCC rejections, priority ordering, sibling-branch symmetry for cancel paths and dispute outcomes) — **PASS**; all 55 error IDs and all 71 enum/state values appear in §1–§4 prose
- Contract 3 (§3 Path Purity): 621 backtick tokens scanned, 0 paths/methods — **PASS**

**Constraint confirmation:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-08-10T09:45:00.000Z

Generation complete. Summary:

## Test counts

**94 tests total, all tagged, zero audit errors** (tag resolution + verbatim-PRD-citation grep both clean; `pytest --collect-only` succeeds; no `skip`/`xfail` markers anywhere).

**Queue A — Difficulty: 18/18 instances, 36 tests (exactly 2 per instance)** — every rule covered: dual_variant_calc (2 instances), combinatorial_formula (2), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2).

**Queue B — Corner: 58/59 non-stub instances, 58 tests (1 each)**; 11 `excluded_because:` stubs not translated (all cross-references verified to resolve to real difficulty instances).

## Per-file breakdown (corner tests / difficulty tests)

- `test_01_org_auth_and_reads.py` — 5/0
- `test_02_request_creation_and_submission.py` — 7/2
- `test_03_interpreter_onboarding_and_availability.py` — 3/2
- `test_04_offer_dispatch.py` — 12/2 (OCC, supersede, max-attempts, eligibility sub-order errors, rate-card 404, quality gate, credit-limit equality, pinned snapshot, VRI estimate, retire-twice + safety-vs-fiscal priority pair)
- `test_05_assignment_lifecycle.py` — 6/4 (state-error bundle, no-show grace, checkout times, double-booking, 2 RBAC + check-in priority pair, VRI capacity)
- `test_06_offer_cycle_and_sweeps.py` — 4/2 (3 sweeps, pagination + offer-cycle-until-UNFILLED)
- `test_07_billing_and_cancellation.py` — 5/10 (billable floor, VRI platform fee, corrected times, 24h tier, verify ownership + estimate-vs-final, rounding order, caps, verification gate, 48h boundary)
- `test_08_invoice_settlement_disputes_credits.py` — 7/6 (+ parallel dimensions, credit apply/void invariant, complaint→waterfall cascade)
- `test_09_strikes_suspension.py` — 3/6 (+ no-show depth-4 cascade, strike threshold, rescind conserved-count)
- `test_10_complaints_quality_reporting.py` — 6/2 (+ quality provisional/final split)

## Skipped instance (1, with reason)

- `Corner/state_machines/decline_from_accepted_returns_assignment_not_offered` — the PRD attaches "(else ERR_ASSIGNMENT_NOT_OFFERED)" only to acceptance prose (§3.5); the error_id for decline-from-ACCEPTED is never verbatim-pinned, so two PRD-only readers could ship different error_ids. Fails the unique-derivability condition; gap left as a gap per the Core rule.

## Infrastructure

`test_helpers/` (9 files): `types.py` (13 entity TypedDicts — StrikeRecord correctly omits `updated_at`/`version` per `common_fields: false`), `api_client.py` (66 endpoint methods on `GenericApiClient`), `api_errors.py` (55 error ids registered via `set_error_http_status_map`), `assertions.py` (per-entity + invoice-invariant checkers + instant-equality comparator tolerant of millisecond rendering), `factories.py`, `constants.py`, `test_users.py` (shared constants + mandatory `make_org_requester_headers`/`make_interpreter_headers` entity-backed builders), `fixtures.py` (composite chains: offered→accepted→confirmed→check-out→verified→issued, VRI scenario, complaint/strike helpers, all identity-threaded).

Two judgment calls worth noting: (1) org `created_at` exact-clock equality was not asserted (PRD never says system timestamps are minted from the logical clock) — only format and the verbatim-covered fields; (2) interpreter version assertions are relative (+1 per mutation, §2.5 verbatim) rather than pinning an initial value the PRD states only for orgs and requests. All files written and verified under `/home/ubuntu/github/CodingPRD/tasks/task_0977_asl_cart_deaf_interpreting/{test_helpers,test_suite}/`; temporary audit/lint artifacts removed.

## Step 6: Generate Implementation — 2026-08-10T09:45:00.000Z

Implementation complete and verified. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_0977_asl_cart_deaf_interpreting/workspace/implementation/`)

- `start.sh` — executable launcher; guarded dependency install (no-op once Flask is importable), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry point, error handlers, blueprint registration, `0.0.0.0:$PORT` (default 10000)
- `core.py` — logical clock (boot default 2026-05-01T00:00:00Z, never wall-clock), empty in-memory store (no seeding), ApiError + full error-ID constants, response envelope (`meta.api_request_id`/`api_request_timestamp` 3-fractional-digit ISO, `response_type`, `data`; pagination in meta), auth/role/ownership helpers, tier-2 body validators, `limit`/`offset` pagination (default 10, 1–100)
- `domain.py` — serializers (computed-on-read: org outstanding balance, interpreter strike count + dual quality scores), all calculations (estimate, cancellation-fee tiers with exact-seconds boundaries, round-per-line-then-sum invoicing, VRI platform fee on actual minutes, capped travel/mileage, strike rolling window, quality aggregation, credit waterfall, coverage/double-booking/VRI-capacity interval checks), cascades (supersede, suspension, no-show strike chain, request cancel tree, PAID→CLOSED bubble), clock sweeps in the pinned order + lazy offer expiry
- `routes_admin.py` — clock, orgs, rate cards, interpreters, certifications, availability windows, strikes
- `routes_flow.py` — requests, offers, assignments (accept/decline/confirm/depart/check-in/check-out/cancel/mark-no-show), encounters
- `routes_money.py` — invoices (generate/issue/void/dispute/resolve-dispute/payments), complaints, credit memos (OCC + waterfall + void reversal), reports

## Endpoint count

**67/67** endpoints implemented and registered — verified against the scaffold's endpoint table by introspecting the Flask URL map.

## Verification

- `start.sh` boots cleanly from a fresh process three consecutive times (~450 ms each, empty store confirmed each boot); install guard makes reboots a no-op.
- 160 ad-hoc end-to-end checks passed across three suites covering: full happy-path lifecycle (org→card→interpreter→cert→activate→window→request→submit→offer(OCC)→accept→confirm→depart→check-in→check-out→verify→invoice→issue→payments→PAID→request CLOSED), exact cent math (estimate 18000+6000+2100; invoice labor/travel/mileage; VRI platform fee on actual minutes), cancellation fee tiers at exact 48h/24h boundaries, supersede + 3-attempt UNFILLED cap, clock sweeps (offer expiry, auto-verify, UNFILLED), suspension + no-show strike cascades, credit waterfall ordering with memo-void reversal, dispute overturn adjustment, validation priority ordering (schema before role, ownership before existence, ADA gate sub-order), fiscal gate with equality allowed, pagination envelopes, and 204 window delete.

One judgment call worth noting: unspecified repeat/invalid transitions without dedicated error IDs (e.g., re-suspend, activate from non-PENDING, void of VOID invoice, assignment cancel from OFFERED) return `ERR_INVALID_REQUEST` (400); PRD-specified errors always take precedence.

## Step 7: Run Tests and Iterate — 2026-08-10T10:05:00.000Z

# Summary

**Exit condition met: all 94 tests pass in all 8 parallel rounds (8 × 94/94, zero failures, zero errors).**

## Iterations run
2 sweeps (16 total round-runs): initial sweep → 12 deterministic failures (identical across all 8 rounds, no flakiness); fixed → second sweep fully green in all 8 rounds.

## Tests deleted
None. Every failing test traced to a PRD-verbatim-covered, uniquely-derivable rule; all 12 failures were test-side bugs (fixtures or assertions), so nothing qualified for deletion under the PRD-First contract.

## Fixes applied to `test_helpers/`
- **`fixtures.py` — `setup_completed_encounter`**: the fixture's canonical scenario (used by every invoice-asserting test, documented in six test docstrings as "130 actual minutes + 90 travel minutes + 12 miles → 24840") omitted the checkout claims entirely, producing a claims-free 19500 invoice. Now passes `checkout_payload={"travel_minutes_claimed": 90, "mileage_claimed": 12}` to `drive_to_checkout`. Root cause of 7 failures (`test_final_invoice_diverges_from_provisional_estimate`, `test_invoice_payment_and_dispute_dimensions_advance_independently`, `test_invoice_final_payment_closes_paid_and_request`, `test_payment_exceeds_amount_due_rejected`, `test_resolve_dispute_overturned_adds_adjustment_line`, `test_credit_application_preserves_amount_due_invariant`, `test_credit_memo_void_restores_amount_due_without_drift`).

## Fixes applied to `test_suite/`
- **`test_04_offer_dispatch.py` — `test_offer_pins_snapshot_surviving_rate_card_retirement`**: pass the documented claims (90 min / 12 mi) to its direct `drive_to_checkout` call, matching its own docstring arithmetic (24840).
- **`test_02_request_creation_and_submission.py` — `test_create_request_defaults_and_computed_credential_mapping`**: pass `ada_context=None` so the field is truly omitted (factory drops `None` keys) and the PRD §3.3 server-side `GENERAL` default is exercised; previously the factory default silently injected `"MEDICAL"`.
- **`test_07_billing_and_cancellation.py` — `test_verify_with_corrected_times_recomputes_billable`**: corrected the expected subtotal 19140 → **23340**. The test's own per-line assertions (LABOR 18000 + TRAVEL_TIME 4500 + MILEAGE 840) sum to 23340 under PRD §3.7's "subtotal is the sum of the per-line rounded amounts"; 19140 was an arithmetic slip no PRD-faithful implementation could produce. Line-level assertions untouched (no weakening).
- **`test_08_invoice_settlement_disputes_credits.py` — `_setup_two_issued_invoices_and_complaint`** (shared by `test_substantiated_complaint_creates_credit_memo` and `test_credit_waterfall_pays_oldest_invoice_and_closes_request`): the fixture filed request B (scheduled June 11) while the logical clock had already advanced to June 13, so the implementation correctly rejected the submission with `ERR_INVALID_SCHEDULE` per PRD §3.3's two-hour lead rule. Restructured to file/offer/confirm both requests at clock 2026-05-01, then serve the two encounters in chronological order; asserted values (inv A 19500 issued 06-13, inv B 24840 issued 06-14, oldest-first waterfall) unchanged.

## Fixes applied to `implementation/`
None. Every implementation behavior the tests tripped on (2h submit lead, per-line rounding, invoice invariant, fiscal gate) was already PRD-correct; the failures were the test artifact mis-expressing its own preconditions or expectations.

## Step 8: Finalize PRD — 2026-08-10T10:12:00.000Z

PRD_FINALIZED.md is produced and verified byte-identical to PRD.md. That is the correct minimal patch under the hard scope: every <step_7_diff> item traced to a rule the PRD already covers verbatim and uniquely, and to test-artifact bugs only — so no PRD edit was warranted, and adding one untraced to a Step 7 fix would violate the hard scope.

## Summary

**Line counts / delta:** PRD.md = 342 lines; PRD_FINALIZED.md = 342 lines; 0% delta (verbatim copy, `diff -q` clean).

**Changes:** None — zero edits committed. Bullets below are the per-candidate-edit pre-edit search log (subject / paths enumerated / decision), one per step_7_diff item, each concluding "PRD already uniquely determines; no edit."

- **§3.5 + §3.7 — no edit — checkout-claims default and zero-line omission (fixtures.py `setup_completed_encounter`; test_04 `test_offer_pins_snapshot_surviving_rate_card_retirement`).** (a) Subject: optionality/defaults of `travel_minutes_claimed`/`mileage_claimed` and downstream TRAVEL_TIME/MILEAGE line composition. (b) Paths enumerated: routes_flow.py:411-419 (check-out parse `opt_int(...,0,minimum=0)`/`opt_num(...,0,minimum=0)`, stored on assignment), routes_flow.py:210 (claims born 0 at dispatch), domain.py:204-205 (serialization), domain.py:501-536 (`build_invoice_line_items`: 240-min/200-mi caps, zero-amount lines omitted except LABOR), domain.py:432-448 (estimate path uses `estimated_mileage`, a different field). (c) None — PRD §3.5 "each optional, each zero or more, each defaulting to zero" plus §3.7 "any line whose amount computes to zero is omitted" uniquely determine both the claims-free 19500 and the claimed 24840 invoices; the failure was the fixture contradicting its own docstring. Pinning claim storage location or capped-line `quantity` semantics was not exercised by the failure and was rejected as a potential false universal claim.
- **§3.3 — no edit — `ada_context` server-side GENERAL default (test_02 `test_create_request_defaults_and_computed_credential_mapping`).** (a) Subject: omitted `ada_context` → GENERAL → `required_credential_level` SCREENED. (b) Paths enumerated: routes_flow.py:43 (`opt_enum(..., "GENERAL")`), routes_flow.py:60 (mapping applied to the resolved value), domain.py:23-24 (REQUIRED_CREDENTIAL map), domain.py:457 (rate-card selection on resolved context), routes_flow.py:76 (listing filter), routes_money.py:430-432 (report mix); core.py:301-304 (`opt_enum` treats explicit JSON null as omitted — noted but not exercised, since the factory drops None keys). (c) None — PRD §3.3 "optional and defaults to `GENERAL`" plus the context→credential mapping table fully determine the behavior; failure was the factory injecting "MEDICAL".
- **§2.6/§3.7 — no edit — subtotal = sum of per-line rounded amounts (test_07 `test_verify_with_corrected_times_recomputes_billable`, 19140 → 23340).** (a) Subject: `subtotal_cents` composition at generation and on dispute adjustment. (b) Paths enumerated: routes_money.py:42-43 (sum of line amounts at generation), domain.py:505-528 (per-line `rhu`), routes_money.py:165-168 (OVERTURNED adjustment re-sums lines), domain.py:609-624 (fee-only invoice), domain.py:548-569 (`recompute_invoice` derives due from subtotal). (c) None — PRD §2.6/§3.7 round-per-line-then-sum uniquely yields 18000+4500+840=23340; 19140 is unreachable under the PRD (pure arithmetic slip).
- **§3.3 — no edit — two-hour submit lead (test_08 `_setup_two_issued_invoices_and_complaint`).** (a) Subject: submit-time schedule validation, boundary inclusivity. (b) Paths enumerated: routes_flow.py:91-110 (`submit_request`: reject when `scheduled_start < now()+2h`; exactly-2h accepted, matching "at least two hours"; sole enforcement site), routes_flow.py:51-52 (creation checks only end>start — no lead rule at creation, consistent with PRD placing it "at submit time"). (c) None — PRD §3.3 verbatim covers the ERR_INVALID_SCHEDULE the fixture tripped by filing request B after the clock had passed its schedule.

Deliverable: `/home/ubuntu/github/CodingPRD/tasks/task_0977_asl_cart_deaf_interpreting/workspace/PRD_FINALIZED.md` (342 lines, identical to PRD.md). Step 7's own conclusion holds up under re-verification: all 12 failures were test-side bugs against PRD-verbatim-covered, uniquely-derivable rules, so the PRD required no pinning edits.

## Step 9: Complete PRD — 2026-08-10T10:25:00.000Z

All 22 hunks landed as intended; line count unchanged (342), size +2,616 chars. Work is complete.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (= `PRD.md`, verified identical) — 342 lines / 59,399 chars; `PRD_COMPLETED.md` — 342 lines / 62,015 chars; char-delta **+2,616** across **22 edited paragraphs** (all inline in-paragraph inserts/revisions; no new sections, no deletions of pinned behavior).

**Counts:** 25 ambiguity-pins, 2 mismatch-revisions.

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, out-of-range `limit`, negative `offset` rejected with `ERR_INVALID_REQUEST` 400 — core.py:345-359
- §2.3 — insert — ambiguity — `created_at` sort ties keep creation (insertion) order — core.py:367-368
- §2.3 — insert — ambiguity — `total_count` is the filtered set size before pagination — core.py:360-363
- §2.4 — insert — ambiguity — clock `to_iso8601` applied verbatim, any instant, no monotonicity check — routes_admin.py:30-31
- §2.5 — insert — ambiguity — `version` starts at 1 on creation — domain.py:49-53 and all constructors
- §2.8 — insert — ambiguity — body-identifier existence list gains the assignment optionally named on a manual strike — routes_admin.py:397-399
- §2.10 — insert — ambiguity — fetch-dependent ownership (submit/cancel/verify/dispute/reopen) necessarily runs after path-resource existence — routes_flow.py:96-98, routes_flow.py:556-559, routes_money.py:129-130
- §3.1 — insert — ambiguity — `credit_limit_cents` is a non-negative integer — routes_admin.py:54
- §3.1 — insert — ambiguity — suspending non-`ACTIVE` / reinstating non-`SUSPENDED` org → `ERR_INVALID_REQUEST` 400 — routes_admin.py:75-76, 88-89
- §3.2 — insert — ambiguity — re-verifying an already-verified certification is allowed (refreshes `updated_at`/`version`) — routes_admin.py:296-297
- §3.2 — insert — ambiguity — activating non-`PENDING_ONBOARD` interpreter → `ERR_INVALID_REQUEST` 400 — routes_admin.py:212-213
- §3.2 — insert — ambiguity — suspending non-`ACTIVE` / reinstating non-`SUSPENDED` interpreter → `ERR_INVALID_REQUEST` 400 — routes_admin.py:230-231, 242-243
- §3.3 — insert — ambiguity — VRI `onsite_address` not required; if supplied, accepted and stored — routes_flow.py:46-50
- §3.3 — insert — ambiguity — `estimated_mileage` is a non-negative number, fractional miles allowed — routes_flow.py:47
- §3.4 — insert — ambiguity — `late_cancel_fee_pct` is a number in [0, 1] — routes_admin.py:132
- §3.4 — insert — ambiguity — rate-card selection ties beyond `created_at` break toward earliest-created — domain.py:464-466
- §3.5 — insert — ambiguity — check-in window bounds both inclusive (`scheduled_start`−30min ≤ now ≤ `scheduled_end`) — routes_flow.py:385-386
- §3.5 — insert — ambiguity — `travel_minutes_claimed` non-negative integer; `mileage_claimed` non-negative number — routes_flow.py:413-414
- §3.6 — insert — ambiguity — direct assignment cancel from any state other than `ACCEPTED`/`CONFIRMED`/`EN_ROUTE` → `ERR_INVALID_REQUEST` 400 — routes_flow.py:447-449
- §3.6 — **revise** — **mismatch** — OFFERED-request cancel bullet said `cancelled_by` `REQUESTER` unconditionally; impl records the actor (`REQUESTER` or `PLATFORM`) — routes_flow.py:119-125, domain.py:676-681
- §3.7 — insert — ambiguity — `corrected_start`/`corrected_end` must be supplied together or both omitted, else `ERR_INVALID_REQUEST` 400 — routes_flow.py:548-550
- §3.7 — **revise** — **mismatch** — verification bubble to `COMPLETED` was unconditional; impl bubbles only when the assignment already stands `COMPLETED` (verifying a still-`ON_SITE` encounter leaves the request `IN_PROGRESS`) — routes_flow.py:575-577 (sweep mirrors it, domain.py:738-743)
- §3.7 — insert — ambiguity — fee-only `CANCELLATION_FEE` line has `quantity` 1, `unit_rate_cents` = fee — domain.py:610-611
- §3.8 — insert — ambiguity — voiding an already-`VOID` invoice → `ERR_INVALID_REQUEST` 400 — routes_money.py:103-104
- §3.8 — insert — ambiguity — voiding an issued invoice recomputes its own `amount_due_cents`/`payment_status`; a `CLOSED` request is not reopened — routes_money.py:118-119, domain.py:559-569
- §3.8 — insert — ambiguity — `ADJUSTMENT` line has `quantity` 1 with `unit_rate_cents` and `amount_cents` equal to the negative adjustment — routes_money.py:165-167
- §3.8 — insert — ambiguity — waterfall ordering: further ties after `issued_at`/`created_at` break by creation order — domain.py:578
- §3.8 — insert — ambiguity — voided memo's `remaining_cents` restored to full `amount_cents`; invoice reversion does not reopen `CLOSED` requests — routes_money.py:350-358
- §3.9 — insert — ambiguity — `credit_pct_override` is a number in [0, 1] — routes_money.py:251

**Notable non-changes (verified already pinned):** twelve-tier validation order incl. tier-9 sub-order (routes_flow.py:148-177), estimate formula with 60-min flat travel / 200-mi mileage cap / round-per-line (domain.py:432-448), response_deadline = min(scheduled_start, offered_at+24h) (routes_flow.py:196-197), buffered double-booking and VRI capacity ≥4th rejection (routes_flow.py:314-345), cancellation fee tiers with inclusive boundaries (domain.py:486-498), 15-min no-show grace with inclusive edge (routes_flow.py:479-481), 365-day inclusive strike window and ≥3 auto-suspend (domain.py:67-74, 664-667), waterfall oldest-first with PAID/EXHAUSTED transitions (domain.py:572-592), quality-score floors (domain.py:77-89), and all report metric definitions (routes_money.py:383-432) — PRD prose already uniquely pinned each.
