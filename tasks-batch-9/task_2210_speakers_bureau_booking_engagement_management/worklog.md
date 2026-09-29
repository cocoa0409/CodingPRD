# Worklog — task_2210_speakers_bureau_booking_engagement_management

## Step 1: Create task directory — 2026-09-01T01:49:06.160Z

Created `tasks/task_2210_speakers_bureau_booking_engagement_management/` and `workspace/` subdirectory (name pre-allocated by the invoking command; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T05:15:00.000Z

All three scaffold artifacts are complete and the linter is clean.

Files:
- `SCAFFOLD.yaml` — 2,862 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,119 lines, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,740 lines, single top-level key `scaffold_corner_design`

Counts

| Item | Count |
|---|---|
| Entities (§1.1) | 14 — Speaker, Client, Inquiry, Proposal, ProposalOption, Engagement, Contract, SpeakerHold, ExclusivityGrant, TravelExpense, Invoice, Remittance, Feedback (immutable), CircumventionClaim |
| State machines (§1.2) | 12 (+2 OCC concurrency rules in §1.2.1) |
| Calculations (§1.3) | 7 |
| Validations (§1.4) | 18 ordered priorities |
| Endpoints (§1.5) | 61 |
| Error catalog (§1.6) | 59 |
| Roles (§1.7) | 4 — BureauAdmin, BookingAgent, Speaker, Client (segregation of duties) |
| §1.8 difficulty design | 9 rules / 24 instances (2,3,3,2,3,3,3,2,3) |
| §1.9 corner design | 9 sections / 78 instances (entities 12, state_machines 14, calculations 11, validations 8, endpoints 6, errors 16, rbac 5, cross_cutting_layers 5, consistency_model 1) — 60 with full test recipes, 18 `excluded_because` stubs deferring to named §1.8 instances |

Design profile: `difficulty_level: expert_plus`; complexity layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, conditional_feature_flags; flat topology; parallel state-machine shape (Engagement carries independent booking and settlement lanes); immediate consistency; `api_prefix: ""`.

Verification
- `scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1,315 calls scanned across 24 + 60 instances)
- All 59 error ids are referenced by at least one instance (0 uncovered).
- Every `excluded_because.difficulty_instance` resolves to an exact §1.8 instance name; no stub carries a `test_recipe`.
- No forbidden concurrency vocabulary anywhere in the three files.
- Two fixes during final pass: endpoint/RBAC-derived corner instances rewritten against exact §1.5 input names; one capture (`$.data.selected_option_id` on Proposal) replaced with `options_count` plus per-option status reads.

Hard constraint honored: no sibling `task_*` directory was listed, read, globbed, or grepped.

## Step 3: Copy shared files — 2026-09-01T05:15:05.000Z

`workspace/INSTRUCTION.md` present and byte-identical to project-root `INSTRUCTION.md` (53 lines) — verified during resume, no re-copy needed.

## Step 4: Generate PRD — 2026-09-01T05:32:00.000Z

PRD generated at `workspace/PRD.md`. **433 lines.** Ends at the last row of the §5 table — no audit footer, no appendix.

Sections: §1 Introduction; §2 Global Specifications & System-Wide Principles (11 subsections: 2.1 Actors and RBAC · 2.2 API Response Structure (verbatim paste) · 2.3 Pagination and Collection Filters · 2.4 Resource Identity, Audit Fields and Versioning · 2.5 The Logical Clock and Whole-Day Arithmetic · 2.6 Money, Percentages and Rounding Discipline · 2.7 Optimistic Concurrency on Inquiries and Engagements · 2.8 Cascade Discipline and Parallel State Dimensions · 2.9 Conserved Roster and Receivable Quantities · 2.10 Path Resolution for Nested Routes · 2.11 The Rejection Ladder (18 ordered bands)); §3 Business Logic & Workflows (9 subsections 3.1–3.9); §4 Endpoint Definitions (61-row table); §5 Error Code Catalogue (59-row table).

Coverage audit (scripted against SCAFFOLD.yaml) — all three Hard Contracts PASS:
- Contract 1 field-name coverage, pass 1 (127 identifiers) → 0 missing; pass 2 (independent 141-token set incl. 14 path params) → 0 missing.
- Contract 2 state machines: 62/62 transitions across 10 machines represented; 54 as explicit FROM → TO arrows, 7 (`OFFERED→WITHDRAWN`, `REJECTED→OFFERED`, `DRAFT/SENT/PARTIALLY_SIGNED→VOID`, `ACTIVE→EXPIRED`, `APPROVED→REIMBURSED`) in cascade prose since no endpoint drives them.
- Contract 2 enums/states: 125 UPPER_SNAKE tokens; 113 verbatim, 12 absentees are constant *names* whose *values* are all present in prose.
- Contract 2 constants: 24-point spot check all present with unit conversions (250,000 cents floor, 21 lead days, 1.20 budget tolerance, 0.0175 surcharge, 0.10/0.35 commission band, 15,000/45,000/90,000/180,000 daily rates, 1.00/1.25/1.60 class multipliers, 0.25/0.22/0.20 tier rates, 4.50/4.00 tier gates, 0.6/0.4 score weights, 0.5/0.3/0.2 rolling weights, 180/365 protection days, 2-strike threshold, 86400, `2026-08-01T00:00:00Z`).
- Contract 2 OCC: both rules in §2.7 with write_endpoint + `expected_inquiry_version` / `expected_engagement_version` + error id + 412, framed purely as stale-version.
- Contract 2 validation ladder: all 18 priorities in §2.11 as explicit numbered ordering with `applies_to` scope enumerated.
- Contract 2 errors: 59 = 59 rows, 0 missing / 0 extra. Endpoints: 61 = 61 rows, 0 missing / 0 extra.
- Contract 3 §3 path purity: 0 violations. No-pseudocode / no-fuzzy-words: 0 hits.

Notes relayed by the subagent:
1. Scaffold `difficulty_level` comment says "59 endpoints" but `endpoints[]` holds **61**; the 61 actual entries were used for §4. (59 is the *error* count — looks like a transposed figure in the comment.)
2. Withheld files never opened: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read, grepped, or referenced; no sibling task directory read. Audit scripts lived in `/tmp`; only `PRD.md` was written into the repo.

## Step 6: Generate implementation — 2026-09-01T05:58:00.000Z

The implementation is complete and verified.

## Files created

All under `workspace/implementation/` — 21 Python modules (~3,080 lines) plus `start.sh` and `requirements.txt`.

**Launcher / infra**
- `start.sh` — `cd "$(dirname "$0")"`, guarded `pip install -q -r requirements.txt` only when Flask is missing, then `exec python3 app.py`. Binds `0.0.0.0:$PORT` (default 10000), `use_reloader=False` so a fresh process is fully deterministic.
- `requirements.txt` — `flask>=2.0`
- `app.py` — `create_app()`, `strict_slashes = False`, 9 blueprints, error handlers mapping `ApiError` -> envelope, 404 -> `ERR_NOT_FOUND`, 405 -> `ERR_METHOD_NOT_ALLOWED`, malformed/400/415 -> 422 `ERR_INVALID_REQUEST`, unexpected -> 500 `ERR_INTERNAL`.

**Foundation**
- `db.py` — 14 in-memory dicts (`speakers, clients, inquiries, proposals, options, engagements, contracts, holds, grants, expenses, invoices, remittances, feedbacks, claims`), a monotonic sequence, and the logical clock (`CLOCK_DEFAULT = 2026-08-01T00:00:00Z`). No file I/O, no seeding — the store is empty on every boot.
- `errors.py` — `ApiError` + 58 error-ID constants with the HTTP status map and default messages.
- `timeutil.py` — ISO parse/format (`.SSSZ`), `whole_days` (floor of seconds/86400), `day_span`, closed-interval intersection.
- `store.py` — `new_row` (uuid4 id, timestamps, `version`, hidden `_seq`), `touch` (one version bump per row per request via `g`), `public` (strips `_`-prefixed keys), `sort_created_asc`.
- `response.py` — envelope builders `ok`, `ok_list`, `error`, `paged` (limit/offset/total_count/has_more).
- `middleware.py` — `roles(...)` decorator (401 before 403), typed FK getters each with its own 404 error ID, parent-walk helpers, ownership predicates.
- `validators.py` — enum tuples, body/field coercers (`req_*`/`opt_*`, cents, enums, datetimes, code lists), pagination and query-param readers.

**Services**
- `services/calc.py` — all money/score math with `Decimal` + `ROUND_HALF_UP`: provisional/final commission, per-line invoice surcharge, retention schedule, rebate, three-way cancellation settlement, travel reimbursable by policy, composite/lifetime/rolling scores, roster tier, protection factor, circumvention commission, budget ceiling.
- `services/lifecycle.py` — cascades and conserved quantities: hold minting/consumption/release with `held_days_count` compensation, grant creation over the half-open `[event_end, event_end + exclusivity_days)` window plus expiry sweep, exclusivity conflict detection, option recount, invoice issuance, remittance creation/payout, contract void, feedback candidate ordering, score recompute + tier transitions, credit-hold inquiry blocking/unblocking.

**Routes (61 endpoints)**
`roster.py` 12 · `pipeline.py` 14 · `engagements.py` 10 · `contracts.py` 4 · `travel.py` 4 · `feedback.py` 2 · `money.py` 7 · `compliance.py` 7 · `clock.py` 1 — matching the PRD §4 table exactly (verified by enumerating `app.url_map`: **61** non-static method/rule pairs).

## Boot verification

Fresh `bash start.sh` with `PORT=18212`:
- `POST /_clock/set_current_utc` -> 200
- `GET /speakers` with no headers -> 401 `ERR_UNAUTHENTICATED`
- `GET /speakers` as `BureauAdmin` -> 200, `{"data": [], "meta": {... "limit": 10, "offset": 0, "total_count": 0, "has_more": false}, "response_type": "array"}`

Server killed by PID afterwards; port confirmed free. No files are written to disk at runtime.

## End-to-end behavioural check

A scratch harness at `/tmp/smoke2210.py` (not part of the deliverable) exercised two full flows and reports **ALL EXPECTATIONS MET**. Values confirmed against the PRD:
- Hold `day_span` = 3 for a 1-day event with `travel_buffer_days` 1.
- Provisional commission 150000 = 600000 x 0.25; after a `0.30` adjustment 180000, final 195000 on gross 650000.
- Grant window `2026-10-10T17:00:00Z` -> `2027-01-08T17:00:00.000Z` (`effective_from_utc` echoed verbatim from the engagement).
- POLICY_A travel reimbursable 112500 = min(200000, max(100000, 45000 x 2 x 1.25)).
- Invoice 775844 = 600000 + 50000 + 112500 lines + 13344 per-line surcharge; partial then final payment drove `settlement_status` to REMITTED and zeroed `pending_remittance_cents`.
- STRICT schedule at 42 days out: retention net 427500 / retention commission 106875, invoice 434981; invoice void compensated the client balance back to 0 and released the speaker's held days.
- Rejection ladder spot-checks passed: 412 stale inquiry version, 409 duplicate speaker in a proposal, 409 travel approval before contract execution, 409 double signature, 403 SoD on commission adjustment, 409 early delivery, 409 overpayment, 409 duplicate feedback, 409 duplicate claim, 409 double cancel.

One incidental note: the only bug the smoke run surfaced was in the harness itself (it reused a stale engagement `version`, and the server correctly answered 412 `ERR_STALE_ENGAGEMENT_VERSION`); no implementation defect was found in that path.

## Step 5: Generate unit tests — 2026-09-01T06:55:00.000Z

All statuses confirmed against the PRD's error table. Work is complete.

**Files created (Stage 1 + Stage 2)**

`test_helpers/`: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/`: `conftest.py` plus 18 test modules — queue A in `test_01`–`test_09`, queue B in `test_10`–`test_18`:
- test_01 commission/score variants (6), test_02 multi-step money formulas (9), test_03 non-linear lifecycles (9), test_04 transitive cascades (6), test_05 rejection-ladder priority (9), test_06 boundary instants (8), test_07 cross-entity gates (9), test_08 temporal overlap (7), test_09 compensating invariants (11)
- test_10 entity basics (14), test_11 state machines (20), test_12 calculations (14), test_13 validations (11), test_14 endpoints (16), test_15 errors (19), test_16 rbac (8), test_17 cross-cutting (10), test_18 consistency (4)

**Total: 190 tests**, all collected cleanly by pytest (`190 tests collected`, no import or collection errors).

**Coverage audit (script-verified against both design indices)**
- 102 instances declared; 18 are stubs (`excluded_because`) → 84 translatable.
- 83 translated, 1 skipped. Every `Design:` tag resolves to a real instance; no tag points at a stub; every test carries exactly one tag as its docstring's last line.
- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 24 instances, 0 stubs → **24/24 translated** (74 tests).
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 78 instances, 18 stubs → 60 translatable, **59 translated, 1 skipped** (116 tests). Per section: entities 12/12, state_machines 11/11, calculations 6/6, validations 8/8, endpoints 6/6, errors 9/9, rbac 3/4, cross_cutting_layers 3/3, consistency_model 1/1.

**The single skip** — `Corner/rbac/client_cannot_read_another_clients_engagement`. The instance asserts that a foreign client's `GET /engagements/{id}` returns 403 `ERR_NOT_RESOURCE_OWNER` and that `GET /engagements` is silently scoped to `total_count 0`. PRD §2.1 scopes the ownership rule to "every `Client`-, `Speaker`- and `BookingAgent`-facing **action endpoint**", and §4 lists `Client` among the authorised roles for both reads with no scoping or per-owner filtering rule anywhere. Neither asserted outcome is uniquely derivable, so the instance was dropped rather than weakened; no placeholder or xfail was emitted.

**Design-vs-PRD divergences resolved in the PRD's favour** (design yaml asserted otherwise; PRD text and the §5 error table win):
- `ERR_OVERPAYMENT`, `ERR_FEE_OUTSIDE_SPEAKER_RANGE`, `ERR_QUOTE_EXCEEDS_BUDGET` asserted at **409**, not 422.
- Losing sibling options asserted as `REJECTED` (PRD §3.3), not the yaml's "DECLINED" — no such option state exists.
- `commission_pct_snapshot` asserted **null** on a freshly selected engagement (PRD §3.4: pricing fields stay null until execution), contradicting the yaml's 0.25.
- Speaker-side cancellation tests assert "nothing billed / settlement `WAIVED` / roster `PROBATION`" but deliberately do **not** assert `retention_net_cents == 0`; the PRD says only that "no retention is computed".

**Verification performed**: a static verifier (`/tmp/verify_2210.py`) checks every `test_helpers` import name exists, every `api.<method>(...)` call matches `ApiClient`'s real signature (positional arity and keyword names), every docstring has exactly one `PRD:` line and one trailing `Design:` line, and every citation survives a literal grep of `workspace/PRD.md` — final run: `tests: 190 problems: 0`. No test was executed against a live server (none was running, and `workspace/implementation/` was not read, per instructions).

## Step 7: Test-fix loop — 2026-09-01T07:35:00.000Z

Green. Five 8-round parallel stability sweeps were run (`prd-bench-local-run --isolation per-test-server`, 8 rounds launched concurrently and joined with `wait`, no `--api-url` so each round claims its own port). The last two sweeps are fully clean: **8/8 rounds x 190/190 passed, twice consecutively** (3,040 test executions, 0 failures, ~257s per round).

### Tests deleted
None. No test asserted a rule the PRD is silent about, and no assertion was weakened, relaxed, skipped or xfailed.

### Fixes applied to `test_suite/`
- `test_16_rbac.py` — `TestEveryRoleExecutesItsOwnOperations::test_the_four_roles_interlock_to_reach_an_executed_agreement` asserted the quotation package was still `ACCEPTED` after contract execution. PRD §3.5 execution fan-out says verbatim: "The quotation package that produced this engagement moves `ACCEPTED → CLOSED`." Assertion corrected to `CLOSED` (STEP 2 — test mis-translated the PRD).
- `test_18_consistency.py` — `TestSelectionCascadeIsVisibleImmediately::test_every_sibling_effect_is_readable_on_the_next_request` asserted `options_count == 2` on a two-option package after one option was selected, while in the same test asserting the sibling is `REJECTED`. PRD §2.9 says verbatim: "On a `Proposal`, `options_count` is the number of that proposal's options whose `status` is `OFFERED` or `SELECTED`" — so the count is 1. Assertion corrected to `1` (STEP 2 — internally contradictory test).

No change was needed in `test_helpers/`.

### Fixes applied to `workspace/implementation/`
Transport-layer only; no endpoint, response field, side effect, header or capability was added or removed, and storage remains in-memory dicts with nothing seeded or persisted.
- `app.py` (`__main__` launcher) — serve the WSGI app with `waitress` instead of the Werkzeug development server, falling back to `app.run()` if waitress cannot be imported. Werkzeug's dev server hardcodes `Connection: close` on every response, so each of the ~50–80 calls a scenario makes opened a fresh loopback TCP connection; across a 190-test run x 8 concurrent rounds (plus other pipelines on the shared host) the 28,232-port ephemeral range filled with TIME_WAIT entries (measured 17.6k–18.5k host-wide, `tcp_tw_reuse=2`), and the kernel intermittently reset a freshly opened connection. That surfaced as one `ConnectionResetError(104)` / `RemoteDisconnected` per round on a random test, with zero application-level errors across 1,520 server boots. Measured effect of the switch: 601 requests now use 3 sockets instead of 601, and the two follow-up sweeps are clean.
- `requirements.txt` — added `waitress>=2.1`.
- `start.sh` — dependency guard widened to `import flask, waitress`, and the `pip install` made non-fatal so the waitress-less fallback path can still boot.

### Diagnostic notes
- Failure detail was read from every `results.${i}.json` for each sweep; the union of failures across all 8 rounds was used each round.
- The connection-reset failure was chased with three controlled reproducers before being attributed: 120 fixture-chain iterations against a persistent server (0 failures), 1,520 kill/respawn cycles across 8 concurrent ports with a full contracted-engagement chain each (~76k requests, 0 failures), and 16,000 reject-before-body-read iterations (~32k requests, 0 failures). It never reproduced below the connection-churn threshold, which is what identified it as ephemeral-port exhaustion rather than a defect in any route.
- Hard constraint honored: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were not read at any point, and no sibling `task_*` directory was inspected. `workspace/PRD.md` was the only contract consulted.

## Step 8: Finalize PRD — 2026-09-01T07:40:00.000Z

**Result: no PRD edit was warranted.** `PRD_FINALIZED.md` exists as a byte-exact copy of `PRD.md` (identical md5, 433 lines each).

## Line counts
- `PRD.md`: 433 lines
- `workspace/PRD_FINALIZED.md`: 433 lines
- Delta: 0 lines, 0.00%

## Changes
None. Every `<step_7_diff>` item traced either to a transport/launcher concern the PRD does not govern, or to a test that mis-read a PRD sentence already present verbatim and already matched by the implementation.

## Per-item analysis log (the pre-edit search that led to "no edit")

**1. `test_16_rbac.py` — quotation package `ACCEPTED → CLOSED` after execution**
- (a) Subject: proposal status transition in the contract-execution fan-out.
- (b) Impl paths enumerated: grepped `CLOSED` across `implementation/` — only two sites exist: `validators.py:41` (enum member) and `routes/contracts.py:116` inside `_execute()`. Read `routes/contracts.py:70-119` (`sign` → `_execute`), the only caller, which sets `proposal["status"] = "CLOSED"` guarded by `proposal["status"] == "ACCEPTED"`. `PRD.md:221` already says verbatim: "The quotation package that produced this engagement moves `ACCEPTED → CLOSED`."
- (c) No wording adjustment: PRD already uniquely determines this and impl agrees. Pure test bug.

**2. `test_18_consistency.py` — `options_count` after selection**
- (a) Subject: the derived `Proposal.options_count` field and every write to it.
- (b) Impl paths enumerated: grepped `options_count` and `recount_options` across `implementation/`. Writers are `routes/pipeline.py:172` (init to 0 at proposal creation), `pipeline.py:257` (`+1` on option add), `pipeline.py:159` (recount on supersession/`OFFERED → WITHDRAWN` sweep), `pipeline.py:360` and `pipeline.py:400` (recount on decline / selection sweeps), and `routes/engagements.py:125` (recount when a speaker-declined engagement returns siblings to `OFFERED`); reader/guards at `pipeline.py:233` (`MAX_OPTIONS`) and `pipeline.py:302` (`< 1` → `ERR_PROPOSAL_NO_OPTIONS`). All funnel into `services/lifecycle.py:118-121`, which counts options whose status is in `("OFFERED", "SELECTED")` — exactly `PRD.md:136` verbatim, and consistent with `PRD.md:193` ("Adding an option increments … by one") since new options start `OFFERED`. Two-option package, one selected + one swept to `REJECTED` => 1.
- (c) No wording adjustment: PRD determines the value; the test was internally contradictory. Pure test bug.

**3. `implementation/app.py` waitress launcher, `requirements.txt`, `start.sh`**
- (a) Subject: the process/WSGI serving layer (HTTP transport, keep-alive, dependency install).
- (b) Impl paths enumerated: read `app.py` in full — the change is confined to the `if __name__ == "__main__"` block (`app.py:73-93`), which only chooses `waitress.serve(...)` vs `app.run(...)` for the same `create_app()` WSGI object; `create_app()` (`app.py:28-67`), the nine blueprints and the three `errorhandler`s are untouched by the diff. Read `start.sh` (guard widened to `import flask, waitress`, `pip install … || true`) and `requirements.txt` (`waitress>=2.1` added). Grepped `PRD.md` for `flask|waitress|werkzeug|wsgi|port|requirements|start.sh|Connection: close|keep-alive`: the PRD never mentions the server process, HTTP connection handling, or dependency installation — those are governed by `INSTRUCTION.md` (bind `0.0.0.0`, honour `PORT`, foreground), whose contract remains satisfied (`exec python3 app.py`, `PORT` default 10000, host `0.0.0.0` on both branches). No endpoint, response field, header, status code or side effect changed.
- (c) No wording adjustment: nothing PRD-observable to pin. Adding launcher prose would have introduced a new, unrequired constraint.

## Step 9: Complete PRD — 2026-09-01T07:55:00.000Z

Verification: 433 lines in both files, no new sections, no new paragraphs — all 35 changes are in-paragraph inserts/revisions across 33 existing lines.

**Line counts / delta:** `PRD_FINALIZED.md` 433 lines / 82,957 chars -> `PRD_COMPLETED.md` 433 lines / 89,583 chars (**+6,626 chars**, 0 lines added).

**Counts:** 25 ambiguity-pins, 10 mismatch-revisions (35 total edits on 33 lines).

### Changes

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` -> `ERR_INVALID_REQUEST`, empty string falls back to default; `created_at` ties broken by insertion sequence; `has_more` formula — `validators.py:245`, `response.py:52`
- §2.3 — insert — ambiguity — filter values compared literally, never enum-checked; unlisted query params ignored — `routes/roster.py:61`
- §2.4 — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` read the host's real clock, not the logical clock; body-supplied instants echoed byte-for-byte, server-derived ones formatted to 3 digits — `store.py:22`, `lifecycle.py:85`
- §2.5 — insert — ambiguity — `current_utc` echoes `to_iso8601` raw, unreformatted — `routes/clock.py:21`
- §2.6 — insert — ambiguity — rates/scores are plain JSON numbers, so `0.20` serialises as `0.2` — `lifecycle.py:236`
- §2.8 — revise — ambiguity — `version` increments **at most once per resource per request** however many effects hit the row — `store.py:38`
- §2.10 — insert — ambiguity — undeclared path -> `ERR_NOT_FOUND` (404), undeclared method -> `ERR_METHOD_NOT_ALLOWED` (405) — `app.py:49`
- §2.11 band 4 — insert — ambiguity — permissive ISO parsing (offset/naive accepted); 5 action endpoints never read the body; 11 free-text fields validated then discarded (only `qualification_note`, hold `reason`, `memo`, `comment` persist) — `timeutil.py:16`, `engagements.py:218`, `contracts.py:61`
- §2.11 band 11 — revise — **mismatch** — terminal check runs *before* the generic transition check for delivery and cancellation (after it for signing/feedback) — `engagements.py:220`, `engagements.py:272`
- §3.1 — insert — ambiguity — `fee_ceiling_cents < fee_floor_cents` -> `ERR_INVALID_REQUEST` — `roster.py:29`
- §3.1 — insert — ambiguity — PATCH fields all optional, ordering re-checked on the merged pair, no-op edit still bumps `version` — `roster.py:96`
- §3.1 — insert — ambiguity — inverted manual blackout accepted with `day_span` 0, no `ERR_EVENT_WINDOW_INVALID` — `timeutil.py:52`
- §3.2 — revise — **mismatch** — unblock cascade fires whenever `credit_status` is set to `GOOD`/`WATCH` regardless of prior value; manual `HOLD` blocks nothing; email is any non-empty string — `roster.py:191`, `roster.py:143`
- §3.2 — insert — ambiguity — `qualification_note` written as null when omitted — `pipeline.py:118`
- §3.3 — insert — ambiguity — duplicate-speaker/rank scans include `REJECTED`/`WITHDRAWN` siblings; the 4-option cap counts only live ones — `pipeline.py:235`
- §3.3 — revise — **mismatch** — presentation checks expiry *before* `options_count` — `pipeline.py:300`
- §3.3 — revise — **mismatch** — proposal decline is **not** expiry-gated — `pipeline.py:352`
- §3.4 — revise — **mismatch** — selection check order (state -> membership -> option state -> credit -> expiry) and non-`OFFERED` option -> `ERR_PROPOSAL_STATE_INVALID` — `pipeline.py:380`
- §3.4 — insert — ambiguity — selection answers `201` with the new `Engagement`, not the package — `pipeline.py:434`
- §3.4 — revise — **mismatch** — `BUREAU` is never written to `cancelled_by`; `on_behalf_of` accepts only `CLIENT`/`SPEAKER` — `engagements.py:265`
- §3.4 — revise — **mismatch** — speaker decline's `ACCEPTED -> PRESENTED` is **not** expiry-gated — `engagements.py:126`
- §3.5 — insert — ambiguity — an engagement may carry several agreements; the first to reach `EXECUTED` prices it — `engagements.py:165`
- §3.5 — insert — ambiguity — send checks contract `DRAFT` first (`ERR_CONTRACT_STATE_INVALID`), then engagement `CONFIRMED` (`ERR_ENGAGEMENT_STATE_INVALID`) — `contracts.py:45`
- §3.6 — insert — ambiguity — submission's bad booking state -> `ERR_ENGAGEMENT_STATE_INVALID`; `settlement_status` not consulted at submission — `engagements.py:196`
- §3.6 — revise — **mismatch** — approval order is settlement-first (`ERR_TRAVEL_EXPENSE_STATE_INVALID`), then booking/executed both -> `ERR_CONTRACT_NOT_EXECUTED` — `travel.py:48`
- §3.7 — insert — ambiguity — delivery's executed-agreement gate is `ERR_CONTRACT_NOT_EXECUTED`, before the clock gate — `engagements.py:224`
- §3.8 — insert — **mismatch** — every cancellation branch voids unexecuted agreements *and* expires active grants — `engagements.py:316`
- §3.8 — revise — **mismatch** — speaker-side `CONTRACTED` branch also voids any lingering unexecuted agreement — `engagements.py:316`
- §3.8 — insert — ambiguity — segregation compares raw `X-User-ID` for any role and is skipped when `owning_agent_user_id` is null; `final_commission_cents` untouched; answers `200` with the Engagement, no adjustment row persisted — `engagements.py:374`
- §3.9 — insert — ambiguity — `rebook_intent` stored null (not false) when omitted — `engagements.py:330`
- §3.9 — revise — ambiguity — third/final descending ordering key is insertion sequence (later-inserted first) — `lifecycle.py:218`
- §3.9 — insert — ambiguity — `variant` other than `ROLLING`/`LIFETIME` -> `ERR_INVALID_REQUEST` — `roster.py:121`
- §3.9 — insert — ambiguity — non-`DELIVERED`/null-snapshot source -> `ERR_ENGAGEMENT_STATE_INVALID`, before the window check — `compliance.py:81`
- §3.9 — insert — ambiguity — `settled_cents` validated then ignored on `UPHOLD`/`DISMISS` — `compliance.py:154`
- §4 — insert — ambiguity — clock setter answers `200 OK` with `data` = `{current_utc}` — `clock.py:21`

All 61 endpoints, the 8 calculation formulas in `services/calc.py`, all state machines, the full 18-band rejection ladder, and every conserved-quantity cascade in `services/lifecycle.py` were walked; no remaining silence or mismatch found.

---

## Pipeline complete — 2026-09-01T07:56:00.000Z

All 9 steps done. Final state: 190/190 tests passing in all 8 rounds of the closing parallel stability sweep. `workspace/PRD_COMPLETED.md` exists on disk.
