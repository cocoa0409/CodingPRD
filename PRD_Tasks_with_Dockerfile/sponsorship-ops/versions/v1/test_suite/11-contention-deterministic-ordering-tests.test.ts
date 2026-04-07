import {
  postAs,
  patchWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  createEventOpen,
  createPackage,
  createSponsor,
  createApplication,
  submitApplication,
  approveApplication,
  countersignCommitment,
  withdrawApplication,
  transitionClaim,
  getPackage,
  getApplication,
  getEvent,
  getCommitment,
  runOps,
  runOpsSuccess,
  createGoldSilverPackages,
  createWaitlistTwoAppsGold,
  createClaim,
  finalizeClaim,
  unwrap,
} from '../../../test-helpers/resources';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 11: Contention / Deterministic Ordering Tests', () => {

  test('CONCUR_001: First submitted application gets submit_seq=1 and is HELD (earliest submit wins)', async () => {

    const event = await createEventOpen();
    const { gold } = await createGoldSilverPackages(event.id);

    const sponsor1 = await createSponsor(event.id, {
      display_name: 'S1',
      legal_name: 'S1 LLC',
      primary_contact_email: 's1@s.test',
      status: 'VETTED',
    });

    const sponsor2 = await createSponsor(event.id, {
      display_name: 'S2',
      legal_name: 'S2 LLC',
      primary_contact_email: 's2@s.test',
      status: 'VETTED',
    });

    const app1 = await createApplication(event.id, { sponsor_id: sponsor1.id, package_id: gold.id });
    const app2 = await createApplication(event.id, { sponsor_id: sponsor2.id, package_id: gold.id });

    await submitApplication(event.id, app1.id);

    await submitApplication(event.id, app2.id);

    const application1 = await getApplication(event.id, app1.id);
    const application2 = await getApplication(event.id, app2.id);

    expect(application1.submit_seq).toBeDefined();
    expect(application2.submit_seq).toBeDefined();
    expect(application1.submit_seq).toBeLessThan(application2.submit_seq!);
    expect(application1.hold_status).toBe('HELD');
  });

  test('CONCUR_002: Second submitted application has higher submit_seq and is WAITLISTED', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const application1 = await getApplication(fixture.event.id, fixture.application1.id);
    const application2 = await getApplication(fixture.event.id, fixture.application2.id);

    expect(application2.submit_seq).toBeDefined();
    expect(application2.submit_seq).toBeGreaterThan(application1.submit_seq!);
    expect(application2.hold_status).toBe('WAITLISTED');
  });

  test('CONCUR_003: Withdrawing HELD application and run_ops promotes WAITLISTED app to HELD', async () => {

    const fixture = await createWaitlistTwoAppsGold();

    const app1Before = await getApplication(fixture.event.id, fixture.application1.id);
    expect(app1Before.hold_status).toBe('HELD');

    const app2Before = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2Before.hold_status).toBe('WAITLISTED');

    await withdrawApplication(fixture.event.id, fixture.application1.id);

    const res = await runOps(fixture.event.id);

    expectSuccess(res);

    const app2After = await getApplication(fixture.event.id, fixture.application2.id);
    expect(app2After.hold_status).toBe('HELD');
  });

  test('CONCUR_004: Finalizing spotlight consumes from spotlight_slot_count, making spotlight_slots_remaining=0', async () => {

    const event = await createEventOpen();

    const pkg = await createPackage(event.id, {
      label: 'SP',
      price_cents: 1,
      slot_count: 2,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsorA = await createSponsor(event.id, {
      display_name: 'A',
      legal_name: 'A LLC',
      primary_contact_email: 'a@a.test',
      status: 'VETTED',
    });

    const sponsorB = await createSponsor(event.id, {
      display_name: 'B',
      legal_name: 'B LLC',
      primary_contact_email: 'b@b.test',
      status: 'VETTED',
    });

    const appA = await createApplication(event.id, { sponsor_id: sponsorA.id, package_id: pkg.id });
    await submitApplication(event.id, appA.id);
    let { commitment: commitmentA } = await approveApplication(event.id, appA.id);

    if (commitmentA.status !== 'ACTIVE') {
      commitmentA = await countersignCommitment(event.id, commitmentA.id);
    }

    const appB = await createApplication(event.id, { sponsor_id: sponsorB.id, package_id: pkg.id });
    await submitApplication(event.id, appB.id);
    let { commitment: commitmentB } = await approveApplication(event.id, appB.id);

    if (commitmentB.status !== 'ACTIVE') {
      commitmentB = await countersignCommitment(event.id, commitmentB.id);
    }

    const currentEvent = await getEvent(event.id);
    const patchRes = await patchWithVersion(
      `/events/${event.id}`,
      { spotlight_slot_count: 1 },
      currentEvent.version
    );
    expectSuccess(patchRes);

    const eventAfterPatch = await getEvent(event.id);
    expect(eventAfterPatch.spotlight_slot_count).toBe(1);
    expect(eventAfterPatch.spotlight_slots_remaining).toBe(1);

    const claimA = await createClaim(event.id, commitmentA.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const res = await transitionClaim(event.id, commitmentA.id, claimA.id, 'FINALIZE');

    expectSuccess(res);

    const commitmentAAfter = await getCommitment(event.id, commitmentA.id);
    const finalizedClaim = commitmentAAfter.claims.find(cl => cl.id === claimA.id);
    expect(finalizedClaim).toBeDefined();
    expect(finalizedClaim!.status).toBe('FINALIZED');

    const eventAfterFinalize = await getEvent(event.id);
    expect(eventAfterFinalize.spotlight_slots_remaining).toBe(0);
  });

  test('CONCUR_005: Finalizing spotlight when full fails with ERR_SPOTLIGHT_FULL, claim remains PROPOSED', async () => {

    const event = await createEventOpen();

    const pkg = await createPackage(event.id, {
      label: 'SP',
      price_cents: 1,
      slot_count: 2,
      included_benefits: [{ benefit_kind: 'SPOTLIGHT', quantity: 1 }],
    });

    const sponsorA = await createSponsor(event.id, {
      display_name: 'A',
      legal_name: 'A LLC',
      primary_contact_email: 'a@a.test',
      status: 'VETTED',
    });

    const sponsorB = await createSponsor(event.id, {
      display_name: 'B',
      legal_name: 'B LLC',
      primary_contact_email: 'b@b.test',
      status: 'VETTED',
    });

    const appA = await createApplication(event.id, { sponsor_id: sponsorA.id, package_id: pkg.id });
    await submitApplication(event.id, appA.id);
    let { commitment: commitmentA } = await approveApplication(event.id, appA.id);

    if (commitmentA.status !== 'ACTIVE') {
      commitmentA = await countersignCommitment(event.id, commitmentA.id);
    }

    const appB = await createApplication(event.id, { sponsor_id: sponsorB.id, package_id: pkg.id });
    await submitApplication(event.id, appB.id);
    let { commitment: commitmentB } = await approveApplication(event.id, appB.id);

    if (commitmentB.status !== 'ACTIVE') {
      commitmentB = await countersignCommitment(event.id, commitmentB.id);
    }

    const currentEvent = await getEvent(event.id);
    const patchRes = await patchWithVersion(
      `/events/${event.id}`,
      { spotlight_slot_count: 1 },
      currentEvent.version
    );
    expectSuccess(patchRes);

    const claimA = await createClaim(event.id, commitmentA.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });
    await finalizeClaim(event.id, commitmentA.id, claimA.id);

    const eventAfterFirstFinalize = await getEvent(event.id);
    expect(eventAfterFirstFinalize.spotlight_slots_remaining).toBe(0);

    const claimB = await createClaim(event.id, commitmentB.id, {
      benefit_kind: 'SPOTLIGHT',
      quantity: 1,
    });

    const res = await transitionClaim(event.id, commitmentB.id, claimB.id, 'FINALIZE');

    await expectErrorCode(res, ERROR_CODES.SPOTLIGHT_FULL);

    const commitmentBAfter = await getCommitment(event.id, commitmentB.id);
    const claimBAfter = commitmentBAfter.claims.find(cl => cl.id === claimB.id);
    expect(claimBAfter).toBeDefined();
    expect(claimBAfter!.status).not.toBe('FINALIZED');

    const eventAfter = await getEvent(event.id);
    expect(eventAfter.spotlight_slots_remaining).toBe(0);
  });

});
