# Worklog — task_2238_public_procurement_bid_protest_debarment

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2238_public_procurement_bid_protest_debarment/` and `workspace/` subdirectory (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T01:00:00.000Z

Scaffold generation for task 2238 is complete. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_2238_public_procurement_bid_protest_debarment/`, generated only from the scenario text plus the skill spec (no sibling task was read).

Contents

- `SCAFFOLD.yaml` (§1.0–§1.7, 2973 lines): `domain_name: public-procurement-protest-debarment`, `api_prefix: /procurement`, `difficulty_level: expert_plus`. 14 entities, 10 state machines, 2 concurrency rules (OCC on `POST /procurement/bids` and on reinstatement-petition creation), 11 calculations, 48 priority-ordered validations, 57 endpoints, 65 errors, 6 roles (ProcurementOfficer, ResponsibilityReviewer, HearingOfficer, DebarmentAuthority, Vendor as `entity_backed:Vendor`, SystemAdmin). Profile: `compliance_audit` / `temporal_windowing`, graph topology, cyclic + parallel-dimension state machines, `segregation_of_duties`, immediate consistency, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key): 19 instances covering all 9 rule_ids (2/2/2/2/3/2/2/2/2) — dual-variant divergences, rounding order, tier-on-base-only, a cyclic hearing continuance walk, parallel bid dimensions, cascade depths 5 and 4, three priority-ladder pairs, two exactly-at-boundary instants, cross-entity gating, and two conservation invariants.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key): 89 instances — 70 with full `setup_api_calls`/`trigger`/`assert` recipes and 19 `excluded_because:` stubs that each cite an existing §1.8 instance by name. Sections: entities 12, state_machines 13, calculations 10, validations 9, errors 28, endpoints 6, rbac 4, cross_cutting_complexity_layers 6, consistency_model 1.

Verification

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(795 calls scanned across 19 §1.8 + 70 §1.9 recipes; 57 endpoints, 14 entities.) Also checked independently: all 89 corner names unique and disjoint from the 19 difficulty names, every stub reference resolves, no stub carries a `test_recipe`, and every non-stub carries `claim_type`, `grounds`, `distinguishing_aspect` and asserts.

Two fixes made during linting, worth flagging: a hardcoded `expected_solicitation_version: "1"` in the unknown-parent-FK corner was replaced with a captured version from an added decoy solicitation, and §1.5 was missing by-id reads for two entities, so `GET /procurement/hearings/{id}` and `GET /procurement/reinstatement-petitions/{id}` were added (endpoint count 55 → 57), which also gives ERR_HEARING_NOT_FOUND / ERR_PETITION_NOT_FOUND clean triggers.

## Step 3: Copy shared files — 2026-09-01T01:05:00.000Z

Copied `INSTRUCTION.md` to `tasks/task_2238_public_procurement_bid_protest_debarment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T01:25:00.000Z

PRD generated at `workspace/PRD.md`.

### Sections written

- **§1 Introduction** — 3 paragraphs (status quo, cost of the current arrangement, what the API enforces; logical clock and `/procurement` mount flagged).
- **§2 Global Specifications** — 10 subsections: 2.1 User and Role-Based Access Control, 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`, verified identical), 2.3 Pagination and Result Ordering, 2.4 Resource Identity / Audit Fields / Logical Clock, 2.5 Path and Foreign-Key Resolution Order, 2.6 Version Pinning on Bid Filing and Reinstatement Filing, 2.7 Monetary and Score Arithmetic, 2.8 Segregation of Duties, 2.9 Cascade Discipline and Immediate Consistency, 2.10 Rejection Precedence (all 48 priorities ordered).
- **§3 Business Logic & Workflows** — 9 subsections: vendor registration and the protest purse; drafting and advertising; question period, addenda and the moving bid due date; sealed bidding, opening and responsiveness; responsibility review; award, stay and execution; protest filing (standing, timeliness, fee, stay); agency record, hearing, decision and ordered remedy (incl. Cascade A and cancellation/resolicitation); suspension, debarment, the debarred-vendor list and reinstatement (incl. Cascade B and subcontractor screening).
- **§4 Endpoint Definitions** — intro paragraph plus 57-row 4-column table.
- **§5 Error Code Catalogue** — 65-row 2-column table. Document ends here; no audit footer.

**498 lines, ~13,700 words.**

### Coverage audit results

- **Contract 1 (Field-Name Coverage): PASS** — 145 distinct identifiers from `entities[].fields[].name`, endpoint `input`, `query_params` and `path_params`; all present verbatim in backticks. First pass surfaced 3 gaps (`bid_id`, `protest_id`, `proceeding_id` — parent-link fields), fixed by adding an explicit nested-parent-link paragraph to §2.5. Re-run: 0 missing.
- **Contract 2 (Rule Coverage): PASS** — verified programmatically against the scaffold: 57/57 endpoints present with 0 method/path mismatches and 0 role-list mismatches; 65/65 error IDs with 0 HTTP-status mismatches; all 48 validation priorities rendered in scaffold order with matching `applies_to` scopes; all 63 state-machine transitions across the 10 machines covered (38 in explicit `X -> Y` arrow form, 25 in prose, each spot-checked against its `preconditions` and `side_effects`); both `concurrency_rules` rendered with parent entity, write endpoint, OCC field, error ID and 412; all 10 calculations rendered with constants translated to prose values, both dual-variant pairs (`as_read`/`corrected`, `interim_suspension_basis`/`final_debarment_basis`) contrasted, and both pinned rounding orders stated; Cascade A (5 hops) and Cascade B (4 hops plus screening fan-out) written hop-by-hop with causal linkage.
- **Contract 3 (§3 Path Purity): PASS** — 1,028 backticked tokens in §3; zero begin with `/`, zero are bare HTTP methods, zero combine method+path; zero raw `/procurement...` strings and zero bare method words anywhere in §3.
- **No-pseudocode check: PASS** — zero occurrences of comparison/aggregate operators or fuzzy quantifiers.

**Three substantive defects found and corrected during audit** (all order-of-magnitude errors in money thresholds, caught by diffing prose against scaffold constants): `HIGH_VALUE_THRESHOLD_CENTS` was written as "five billion cents / fifty million dollars" instead of 500,000,000 cents / five million dollars; the administrative-fee ladder boundaries were written as "one billion" and "five billion" cents instead of 100,000,000 and 500,000,000. All money thresholds now use grouped digit forms. §3 was also consolidated from 12 to 9 subsections to sit inside the spec's grouping range, with cross-references re-verified.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T02:05:00.000Z

Test generation for task_2238 is complete.

### Files written

**Stage 1 — `test_helpers/` (9 files)**
`types.py` (UserRole + 23 enums, TypedDicts for 10 mutable entities and 4 append-only rows), `api_errors.py` (all 65 error ids + §5 HTTP status map, registered via `set_error_http_status_map`), `api_client.py` (`ApiClient(GenericApiClient)`, 57 endpoint methods under `/procurement`), `constants.py` (every PRD-pinned rate, tier, weight, cap and window), `test_users.py` (10 users across 6 roles + header builders), `factories.py` (27 payload factories with monotonic id counters), `assertions.py` (envelope/audit-field/money/score/pagination assertions), `fixtures.py` (5-tier state builders: clock, 33 write primitives, 11 reads, 11 scenario composites), `__init__.py` (barrel). `import test_helpers` verified clean.

**Stage 2 — `test_suite/` (conftest + 20 files)**
163 test functions, 172 collected cases (`pytest --collect-only` succeeds with zero errors; `compileall` clean).

### Counts per queue

| Queue | Tests | Instance coverage |
|---|---|---|
| A (Difficulty, §1.8) | 55 | 19/19 instances, all with >=2 tests |
| B (Corner, §1.9) | 108 | 67/70 non-stub instances |

All 19 `excluded_because:` corner stubs were left untranslated; every stub's `difficulty_instance` cross-reference resolves.

### Audits — clean

- Design tags: 163/163 tests carry exactly one `Design:` line as the final docstring line; zero untagged, dual-tagged, malformed, wrong-rule, wrong-section, or stub-translated tags.
- PRD citations: 163/163 tests quote at least one full, verbatim, rule-bearing PRD sentence (machine-verified as an exact substring of `workspace/PRD.md`, endpoint-table titles excluded).
- Scaffold-leak grep over `test_suite/*.py`: no matches.

Two auditor bugs were found and fixed during verification (leading `"` not stripped from candidate sentences; two adjacent quoted sentences merged into one candidate) — no test was changed as a result.

### Instances skipped (3, all queue B, per the PRD-first filter)

1. `Corner/errors/corner_award_creation_with_an_emptied_candidate_set_is_rejected` — the design requires the solicitation to still be `AWARD_PENDING` after an interim-suspension cascade empties the candidate set, so award creation would fail at §2.10 priority 42 with `ERR_NO_APPARENT_LOW_BIDDER`. PRD §3.4 says ranking re-runs "inside every cascade that changes any bid's `responsiveness_status`" and "a solicitation sitting in `AWARD_PENDING` whose candidate set empties falls back to `EVALUATION`", so priority 10 fires first with `ERR_INVALID_SOLICITATION_STATE` — the id the instance explicitly forbids. The pinned precondition cannot exist under the PRD.
2. `Corner/endpoints/corner_second_resolicit_of_the_same_predecessor_is_rejected` — resolicits an already-`RESOLICITED` predecessor and forbids `ERR_INVALID_SOLICITATION_STATE`, but §2.10 step 10 (state admissibility, which applies to resolicitation) precedes step 19, and §3.8 requires the predecessor to be `CANCELLED`. Asserted outcome is not uniquely derivable.
3. `Corner/endpoints/corner_bid_list_filters_and_pages_by_responsiveness_status` — pins the paged row by ascending `evaluated_price_cents`, but §2.3 orders every list by `created_at` ascending and names only three overrides (none of them bids); §3.4 gives bids filters and no ordering. Under the PRD the pinned page lands on a different row.

### Notable deviations flagged by generators (all documented in-file, none weakening an assertion)

- `test_16`: one instance's clock moved to `2027-09-01` so the design's own stated "outside the prior occupancy interval" precondition is actually true (the yaml's `2026-09-01` would have tripped `ERR_ACTIVE_PROCEEDING_EXISTS` first); yaml placeholder path ids that were not valid UUIDs were replaced with well-formed non-existent UUIDs.
- `test_08`: dropped an assertion on a non-existent `Solicitation.bid_count` field, substituting the yaml's own sibling assertion (empty bid list).
- `test_18`/`test_20`: substituted PRD-specified fields/filters where the yaml named undocumented ones (`effective_question_deadline_utc`, `solicitation_number` as a list filter).
- `test_15` carries one PRD ambiguity worth knowing about: a `challenged_bid_id` supplied on `SOLICITATION_IMPROPRIETY` has no error id pinned to §3.7's conditional-nullity sentence, so the test asserts the only PRD-reachable id, `ERR_BID_NOT_ON_SOLICITATION`.

Nothing under `workspace/implementation/` was read or created.

## Step 6: Generate implementation — 2026-09-01T02:05:00.000Z

The implementation is complete and validated.

### Files written

All under `workspace/implementation/` (17 files):

- `start.sh` (executable), `app.py`, `requirements.txt` (`flask`)
- Core: `store.py` (in-memory dicts only, no seeding, no disk I/O), `envelope.py`, `validation.py`, `serializers.py`, `errors.py` (66-entry catalogue), `util.py`, `calc.py`, `services.py`
- Routes: `routes/{__init__,clock,vendors,solicitations,bids,awards,protests,hearings,debarment,screenings}.py`

### Endpoint count

**57 endpoints**, matching PRD §4 one-for-one: clock 1, vendors 6, solicitations 13, bids 6, awards 4, protests 10, hearings 4, debarment/reinstatement 10, screenings 3.

### Architecture notes

- Storage is a single `db = {collection: {}}` dict in `store.py`; every boot starts empty. Logical clock defaults to `2026-08-01T00:00:00Z`.
- Version discipline is centralized: handlers mutate through `validation.set_field`/`touch`, which record rows in a per-request dirty set in `flask.g`; `finalize()` bumps `updated_at` + `version` exactly once per row before serialization, so §2.9 holds automatically across cascades. Journal rows (`MandatoryRequirement`, `Addendum`, `QuestionSubmission`, `AgencyRecordItem`) are created unversioned and never expose `updated_at`/`version`.
- Money uses `Decimal` + `ROUND_HALF_UP` with the PRD's pinned rounding order (protest fee: round all three components then sum; award: round fee, then reserve on base + rounded fee).

### Smoke-test result

Three suites, each against a server booted via `bash start.sh`, all passing:

- `/tmp/smoke2238.py` -> `SMOKE OK` — full lifecycle: draft/issue/addendum (7-day extension moving both deadlines), stale-version 412, bid opening + as-read ranking, informality loading 2250 -> evaluated 902250, composite 70 -> AWARD_PENDING, admin fee 13534, protest fee 40338 with an ACTIVE stay blocking execution, hearing room conflict, SUSTAINED/CORRECTIVE_ACTION Cascade A voiding the award and reverting bids and reviews, interim suspension Cascade B, severity 75 -> 36 months -> end 2029-09-25, screening `BLOCKED_DEBARRED`, petition premature -> 18 months served -> GRANTED restoring eligibility, cancel/resolicit.
- `/tmp/smoke2238b.py` -> `SMOKE B OK` — fresh-boot emptiness (every collection `total_count == 0`), material-addendum gate, extension cap, continuance/docket capacity (540 min rejected, 480 accepted, third continuance refused), withdrawal refund zeroing escrow, pagination meta and `has_more`.
- `/tmp/smoke2238c.py` -> `SMOKE C OK` — standing/402 fee-balance/trigger-missing/ownership precedence on protest filing, timeliness at exactly the deadline vs. +1 ms, `ERR_DUPLICATE_FACTOR_CODE`, interim threshold, double-docketing, response window, hearing-rights exhaustion, severity floor, DISMISSED compensating the interim strike, stale proceeding version 412, and 404 identities for petitions/proceedings.

No implementation defects were found by any suite. All test servers have been stopped; nothing was created under `test_helpers/` or `test_suite/`.

## Step 7: Run tests and iterate — 2026-09-01T13:55:00.000Z

Sweep is clean. Root cause of the remaining flake was established as external, not a defect in this task.

### Diagnosis of the coordinator-reported failure (final round)

The coordinator's stale-pooled-socket hypothesis was **disproved**, and so was the server-crash hypothesis. Evidence:

1. Reproduced it (sweep 4, 6/8 clean, rounds 3 and 7 at 171/172) — but on a **different** test (`test_08_boundary_instants_and_docket_capacity.py::TestHearingOfficerDailyDocketCeiling::test_docket_total_of_exactly_four_hundred_eighty_minutes_is_accepted`), same `ConnectionResetError(104)`. So it is not test-specific.
2. The reset was **mid-test, not on the test's first request** (traceback: 14 requests served, then `create_hearing` in `_second_hearing_response` reset) — which rules out a pooled keep-alive socket left over from the previous per-test server restart.
3. No crash: `/tmp/prd_bench_server_<port>.log` contains no traceback, no `Address already in use`, no Flask 500. The server process was terminated by an **external signal** — the log shows shell-emitted `Killed` (SIGKILL) and, elsewhere, `Terminated` (SIGTERM). `app.py` has no reloader/child process, and the kernel log shows no OOM kill (126 GB RAM, 108 GB available).
4. Decisive: every access-log line was timestamped for all 8 rounds. Each round has **exactly one >=3 s gap, at the same wall-clock second — 13:34:29-31 — on 8 different ports**. The server logs belonging to *another pipeline's* concurrent sweep (ports 32879, 34067, 38495, 41165, 42957, 50605, 56455, 57569) **all 8 show the identical 3-5 s gap at 13:34:29-31**. A single host-wide event killed every `app.py` server on the box across at least three pipelines / 16+ servers.

So this is a cross-pipeline broad `pkill`-style cleanup landing mid-run instead of at startup. In the 6 rounds that still passed, the kill landed between tests and `pytest_plugin._restart_server` respawned transparently (visible as spawned-but-zero-request server blocks); in the 2 failing rounds it landed while a request was in flight. The same mechanism explains the coordinator's sweep, where all 8 rounds — being in lockstep — were mid-request on the same test when one such kill fired.

No client-side mitigation is possible or appropriate: once the server is SIGKILLed, its in-memory state is gone, so a retry/session-reset in `test_helpers` would only convert a connection error into a wrong-state failure while masking genuine crashes. The remedy for interference is to re-run. **Nothing was changed in that round** (no implementation, test_suite, or test_helpers edits).

### Final sweep — clean
8 parallel rounds, `--isolation per-test-server`, fresh ports, no external kill event in the window: **172/172 in all 8 rounds**. `workspace/implementation/results.{1..8}.json` are on disk. (Independently re-verified by the orchestrator: 8 files, all 172/172, 0 failed.)

### Full Step 7 summary (all iterations)

Iteration 1: 116/172 -> Iteration 2: 170/172 -> Iteration 3: 172/172 -> Iteration 4 (verification, external kill event): 6 rounds 172/172, 2 rounds 171/172 -> Iteration 5: **172/172 x 8**.

Tests deleted: **none** (no STEP 1a/1b deletion was warranted).

test_helpers fixes (1):
- `test_helpers/fixtures.py::fund_vendor` demanded HTTP 201 from `POST /procurement/vendors/{id}/fee-deposits`. PRD §3.1 makes a deposit a mutation of the vendor ("credits the vendor's `protest_fee_balance_cents` ... and bumps the vendor's `version`") with no `FeeDeposit` entity, and PRD §4 says modify-endpoints return 200. Changed to expect 200. This single fixture bug caused 55 of the 56 iteration-1 failures (the TRIAGE HINT held).

test_suite fixes (2):
- `test_suite/test_13_lifecycle_state_transitions.py` — STEP 1c partial coverage: removed only the assertion `stored["cancellation_reason"] == ...`. PRD §3.8 names `cancellation_reason` solely as cancel input and never declares it as a Solicitation response field. The `status == "CANCELLED"` assertion was kept.
- `test_suite/test_15_validation_rules.py::test_challenged_bid_from_another_solicitation_is_refused` — STEP 2 test bug: it filed with `SOLICITATION_IMPROPRIETY` grounds *and* a `challenged_bid_id`, which PRD §3.7 forbids ("must be null for the other three grounds"), so the server correctly answered `ERR_INVALID_REQUEST` and precedence step 45 was unreachable. Rebuilt the setup to be PRD-faithful: `RESPONSIVENESS_DETERMINATION` grounds, a bid on the protested solicitation (for `ACTUAL_BIDDER` standing), and a foreign bid carried through its responsiveness determination (the trigger event). The exact `ERR_BID_NOT_ON_SOLICITATION` assertion and all no-side-effect assertions were left untouched; the implementation check was not weakened.

Implementation fixes (1):
- `workspace/implementation/routes/protests.py:33` — `REMEDIES` omitted `"NONE"`, an enum member PRD §3.8 names verbatim ("`NONE` is the remedy recorded with a denial"), so a decision body carrying `remedy_code: "NONE"` was rejected with `ERR_INVALID_REQUEST` ahead of `ERR_HEARING_NOT_CONCLUDED`. Added `"NONE"`.

No endpoint, field, side effect, or seeded data was added; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-09-01T14:05:00.000Z

Done. `PRD_FINALIZED.md` is in place at `workspace/PRD_FINALIZED.md`.

### Size

- PRD.md: 497 lines / 103,316 chars; PRD_FINALIZED.md: 497 lines / 104,217 chars.
- Line delta 0.0% (all three edits are inline additions inside existing prose paragraphs); character delta +901 (+0.87%).

### Changes (3)

- **§3.1 (Registering Vendors and Funding the Protest Purse)** — insert — pinned that a fee deposit creates no deposit row (no `FeeDeposit` entity) and therefore answers with the §4 modify status HTTP 200 carrying the updated vendor in `data` — `implementation/routes/vendors.py:68-78`.
- **§3.8 (remedy sentence)** — revise — pinned `NONE` as one of the four recognised `remedy_code` enum members, so a decision body carrying `remedy_code: "NONE"` clears §2.10 step 3 instead of being rejected with `ERR_INVALID_REQUEST`, and later preconditions are reached — `implementation/routes/protests.py:33,345`.
- **§3.8 (cancellation paragraph)** — insert — pinned that `cancellation_reason` is request input only: not persisted on the solicitation and absent from the solicitation payload — `implementation/routes/solicitations.py:342-349`, `implementation/serializers.py:43-55`.

Item 3 of `<step_7_diff>` (the `test_15` rebuild) produced **no** PRD edit: it was a pure test bug — PRD §3.7 already forbids `challenged_bid_id` on `SOLICITATION_IMPROPRIETY`, and the impl's ordering (standing -> trigger -> timeliness -> `ERR_BID_NOT_ON_SOLICITATION`) matches §2.10 steps 23/31/32/45 at the tested site.

### Per-edit pre-edit search log

**Edit 1 — fee-deposit response**
- (a) Subject: the fee-deposit endpoint's HTTP status / response body, and whether any deposit entity exists.
- (b) Paths enumerated and read: `routes/vendors.py:68-78` (only deposit handler; `("obj", vendor, serializers.vendor, 200)`); `store.py:17-31` `COLLECTIONS` (no deposit/journal collection); `validation.py:91-102` `render` + `envelope.object_response` (data = serialized row); every other writer of `protest_fee_balance_cents` — `routes/vendors.py:39` (init 0), `routes/protests.py:196` (filing debit), `routes/protests.py:99-107` `_refund` (withdrawal/sustain re-credit); `serializers.vendor`; §4 table row for `POST /procurement/vendors/{id}/fee-deposits`.
- (c) Adjustment: scoped the sentence to "A deposit ..." so it says nothing about the debit/refund paths that touch the same balance, and phrased the status as "the modify-endpoint status of §4, HTTP 200" so it reinforces rather than competes with §4's general rule; kept `version`/`updated_at` wording untouched (already correct via `v.touch`).

**Edit 2 — `remedy_code` enum membership**
- (a) Subject: accepted values of `remedy_code` on `POST /procurement/protests/{id}/decision`.
- (b) Paths enumerated and read/grepped (`grep -rn "remedy_code"` over `implementation/`): `routes/protests.py:33` (`REMEDIES` now includes `"NONE"`), `:345` (`opt_enum`, so absent/null allowed), `:346-349` (required only when `outcome == "SUSTAINED"`), `:366-377` (DENIED forces stored `NONE` whatever was supplied; SUSTAINED stores the supplied value, refunds, then cascades), `services.py:234-251` `sustained_protest_cascade` (branches on `CORRECTIVE_ACTION`; **every other value, including `NONE`, falls into the `else` branch that cancels the solicitation**), `serializers.py:120` (field exposed), `test_helpers/factories.py:322` (default payload sends `NONE`).
- (c) Adjustment: because of the `services.py:249` else-branch, deliberately did **not** write that `NONE` is rejected on a sustain, nor that it is inert there; wording was narrowed to enum recognition plus "later preconditions ... are reached and evaluated normally", leaving the sustain-with-`NONE` outcome as under-determined as PRD.md already leaves it, and leaving the existing "is not a remedy a sustaining officer supplies" clause verbatim.

**Edit 3 — `cancellation_reason` persistence**
- (a) Subject: whether `cancellation_reason` is stored on / returned by the Solicitation.
- (b) Paths enumerated and read/grepped (`grep -rn "cancellation_reason"`): `routes/solicitations.py:340-349` (only occurrence — `v.req_str` validates then discards; returns the updated solicitation at 200), `services.py:217-231` `cancel_solicitation` (the shared cascade path, invoked with no reason argument from `sustained_protest_cascade`), `serializers.solicitation` field list (no such key), solicitation row construction at `routes/solicitations.py:88-105` and `:381-398` (no such key).
- (c) Adjustment: phrased as "an input of that request and nothing more" and placed before the cascade sentence, so it does not imply the cascade path supplies or records a reason; requiredness of the field was left as PRD.md's "supplying a `cancellation_reason`" already implies (matches `v.req_str`).

## Step 9: Complete PRD — 2026-09-01T14:25:00.000Z

Done. `PRD_COMPLETED.md` is in place at `workspace/PRD_COMPLETED.md`.

### Size

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 497 | 497 (unchanged — no new paragraphs, no new sections) |
| chars | 103,841 | 112,581 (**+8,740**) |

37 existing lines edited in place; **41 changes total — 31 ambiguity-pins, 10 mismatch-revisions.**

### Mismatch revisions (PRD asserted something implementation contradicts)

- §2.10 step 3 — revise — mismatch — hearing window "strictly after" relaxed to "does not precede"; a zero-length window passes the shape check — `implementation/util.py:74`
- §3.8 (scheduling) — revise — mismatch — same relaxation stated where the hearing window is described, noting a zero-minute window books no docket time — `implementation/util.py:74`
- §3.4 (ranking) — revise — mismatch — dropped the claim that price + `created_at` is unique; insertion order is a real third sort key — `implementation/services.py:133`
- §3.4 (ranking) — revise — mismatch — the "AWARD_PENDING falls back when the candidate set empties" rule replaced: recomputation never moves `status`; only the §3.9 vendor cascade reverts, and it fires whenever the apparent low bidder *changed* — `implementation/services.py:136`, `implementation/services.py:277`
- §3.7 (challenged bid) — revise — mismatch — a foreign challenged bid supplying no trigger event yields `ERR_BID_NOT_ON_SOLICITATION` ahead of `ERR_PROTEST_TRIGGER_EVENT_MISSING`, but still behind `ERR_PROTEST_UNTIMELY` — `implementation/routes/protests.py:158`
- §3.8 (Cascade A) — revise — mismatch — hops 2-5 are skipped entirely when no award left `PENDING_STAY`/`EXECUTED` or the solicitation is not `AWARD_PENDING`/`AWARDED` — `implementation/services.py:247`
- §3.8 (CANCELLATION) — revise — mismatch — the cancel hop is unconditional from any state, `AWARDED` included, and runs whether or not an award was voided — `implementation/services.py:249`
- §3.8 (cancellation destination) — revise — mismatch — the cascade route to `CANCELLED` is reachable from any protestable state, not only `EVALUATION`/`AWARD_PENDING` — `implementation/services.py:251`
- §3.9 (hearing-rights track) — revise — mismatch — removed the claim that either branch "records" being heard / rights exhausted; `hearing_summary` is discarded and only the status changes — `implementation/routes/debarment.py:160`
- §3.9 (granted petition) — revise — mismatch — the version list was exhaustive but omitted the proceeding, whose `strikes_applied` write bumps its `version` while `status` stays `DEBARRED` — `implementation/routes/debarment.py:314`

### Ambiguity pins (PRD was silent)

- §2.2 — insert — ambiguity — `api_request_timestamp` comes from wall clock, not the logical clock — `implementation/envelope.py:17`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` rejected; empty-valued query params treated as absent; accepted `include_suspended` spellings and `as_of_utc` parse failure; `offset` past `total_count` returns an empty page with the true total — `implementation/validation.py:274`, `:299`, `:304`, `:327`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — `implementation/store.py:85`
- §2.7 — insert — ambiguity — decimal score fields render as bare JSON numbers with no trailing zeros (60.00 -> `60`) — `implementation/util.py:107`, `implementation/serializers.py:21`
- §2.9 — insert — ambiguity — a row is dirtied only by a value that actually changes; a no-op recomputation leaves `version`/`updated_at` alone — `implementation/validation.py:50`
- §3.1 — insert — ambiguity — `contact_email` gets no format check beyond non-emptiness — `implementation/routes/vendors.py:29`
- §3.2 — insert — ambiguity — `mandatory_requirements` is required but may be empty; `predecessor_solicitation_id` must resolve (`ERR_SOLICITATION_NOT_FOUND`) — `implementation/routes/solicitations.py:71`, `:75`
- §3.2 — insert — ambiguity — draft initial values (five nulls, three zeros, `version` 1) — `implementation/routes/solicitations.py:88`
- §3.2 — insert — ambiguity — requirements are listable with a `materiality` filter — `implementation/routes/solicitations.py:240`
- §3.3 — insert — ambiguity — a question on a `DRAFT` solicitation also yields `ERR_QUESTION_PERIOD_CLOSED` — `implementation/routes/solicitations.py:265`
- §3.3 — insert — ambiguity — the addendum echoes `new_requirement_codes` as normalised objects — `implementation/routes/solicitations.py:202`
- §3.3 — insert — ambiguity — a named question not in `PENDING` is left untouched, without error — `implementation/routes/solicitations.py:210`
- §3.4 — insert — ambiguity — `corrected_total_price_cents` must be strictly positive — `implementation/routes/bids.py:107`
- §3.4 — insert — ambiguity — a `NONRESPONSIVE` determination still stores the corrected price but leaves `evaluated_price_cents`/`informality_loading_cents` alone — `implementation/routes/bids.py:142`
- §3.5 — insert — ambiguity — `weight_profile`, `strike_penalty_points` and `notes` are persisted review fields — `implementation/routes/bids.py:193`
- §3.6 — insert — ambiguity — award creation requires the solicitation in `AWARD_PENDING` — `implementation/routes/awards.py:27`
- §3.6 — insert — ambiguity — `administrative_fee_rate` renders as a plain JSON number — `implementation/serializers.py:158`
- §3.6 — revise — ambiguity — either wrong award state or wrong solicitation state on execute reports `ERR_INVALID_SOLICITATION_STATE` — `implementation/routes/awards.py:70`
- §3.7 — insert — ambiguity — missing trigger for `RESPONSIVENESS_DETERMINATION`, `EVALUATION_ERROR` and `SOLICITATION_IMPROPRIETY` -> `ERR_PROTEST_TRIGGER_EVENT_MISSING` — `implementation/routes/protests.py:56`, `:62`, `:89`
- §3.7 — insert — ambiguity — stay override needs `stay_status == ACTIVE` (else `ERR_INVALID_PROTEST_STATE`); `urgency_justification` not persisted — `implementation/routes/protests.py:415`, `:410`
- §3.7 — insert — ambiguity — `withdrawal_reason` not persisted — `implementation/routes/protests.py:386`
- §3.8 — insert — ambiguity — record-item filing requires an open protest; record and hearing lists take `item_type` / `status` filters — `implementation/routes/protests.py:237`, `:262`, `:326`
- §3.8 — insert — ambiguity — concluding advances the protest only if it still stands `HEARING_SCHEDULED`; otherwise only the hearing's version moves — `implementation/routes/hearings.py:93`
- §3.8 — insert — ambiguity — the decision `rationale` is not persisted — `implementation/routes/protests.py:344`
- §3.8 — insert — ambiguity — `apparent_low_bid_id` is recomputed a second time after the hop-4/5 reversions, letting a formerly `NONRESPONSIBLE` bid re-enter — `implementation/services.py:214`
- §3.8 — insert — ambiguity — a sustained outcome with `remedy_code` `NONE` is recorded verbatim and takes the `CANCELLATION` branch — `implementation/services.py:249`
- §3.8 — insert — ambiguity — resolicitation revalidates question-deadline-before-bid-due, copies `title`/`issuing_agency_code`/`estimated_value_cents`, and returns the successor at 201 — `implementation/routes/solicitations.py:359`, `:383`, `:407`
- §3.9 — insert — ambiguity — the merits `rationale` is not persisted — `implementation/routes/debarment.py:179`
- §3.9 — insert — ambiguity — debarment hop 1 sets `active_debarment_id` and `suspension_reason_code` (to `cause_code`) exactly as an interim suspension does — `implementation/services.py:312`
- §3.9 — insert — ambiguity — dismissal never re-runs severity: the interim-variant `severity_score`/`mitigating_credit_points` stand and the floor is never consulted — `implementation/routes/debarment.py:211`

Notes: narrative check orderings inside §3 that read differently from §2.10 were left alone — §2.10 is declared authoritative and every ordering traced in `routes/` matches it (bid review, award creation, continuance, resolicitation included). The §4 endpoint table and §5 error catalogue already match the implementation exactly (58 routes, no extras, no gaps), so neither was touched.
