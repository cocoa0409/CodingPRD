import { v4 as uuidv4 } from 'uuid';
import { Response } from 'supertest';
import { getAs, postAs, patchWithVersion, putWithVersion } from './api-client';
import { expectSuccess, extractErrorCode } from './assertions';
import {
  EventPosture,
  SponsorStatus,
  PackageStatus,
  ApplicationStatus,
  CommitmentStatus,
  ClaimStatus,
  HoldStatus,
  BenefitKind,
  ApplicationAction,
  PackageAction,
  CommitmentAction,
  ClaimAction,
  Role,
  DEFAULT_ROLE,
} from './constants';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

export function unwrap<T = any>(body: any): T {
  return body && typeof body === 'object' && 'data' in body ? body.data : body;
}

export function pickId(body: any, keys: string[]): string {
  for (const key of keys) {
    const value = body?.[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  throw new Error(`Could not find id in response. Looked for: ${keys.join(', ')}`);
}

export function asArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value?.items)) return value.items;
  if (Array.isArray(value?.data)) return value.data;
  return [];
}

export interface IncludedBenefit {
  benefit_kind: BenefitKind;
  quantity: number;
}

export interface Event {
  id: string;
  name: string;
  posture: EventPosture;
  ops_run_index: number;
  spotlight_slot_count: number;
  spotlight_slots_remaining: number;
  version: number;
}

export interface Package {
  id: string;
  label: string;
  price_cents: number;
  slot_count: number;
  slots_remaining: number;
  included_benefits: IncludedBenefit[];
  status: PackageStatus;
  version?: number;
}

export interface Sponsor {
  id: string;
  display_name: string;
  legal_name: string;
  primary_contact_email: string;
  status: SponsorStatus;
  version: number;
}

export interface Application {
  id: string;
  sponsor_id: string;
  package_id: string;
  status: ApplicationStatus;
  hold_status?: HoldStatus;
  hold_expires_on_ops?: number;
  submit_seq?: number;
  commitment_id?: string;
  note?: string;
  version: number;
}

export interface BenefitsLeft {
  LEAD_SCANS?: number;
  STAGE_MINUTES?: number;
  SPOTLIGHT?: number;
}

export function normalizeBenefitsLeft(benefitsLeft: any): BenefitsLeft {
  if (!benefitsLeft) return {};

  if (!Array.isArray(benefitsLeft)) {
    return benefitsLeft as BenefitsLeft;
  }

  const result: BenefitsLeft = {};
  for (const item of benefitsLeft) {
    if (item.benefit_kind && typeof item.quantity === 'number') {
      (result as any)[item.benefit_kind] = item.quantity;
    }
  }
  return result;
}

export interface Claim {
  id: string;
  benefit_kind: BenefitKind;
  quantity: number;
  status: ClaimStatus;
}

export interface Commitment {
  id: string;
  sponsor_id: string;
  package_id: string;
  status: CommitmentStatus;
  activation_deadline_on_ops?: number;
  benefits_left: BenefitsLeft;
  claims: Claim[];
  version?: number;
}

export interface CreateEventInput {
  name?: string;
  spotlight_slot_count?: number;
}

export async function createEvent(
  input: CreateEventInput = {},
  role: Role = DEFAULT_ROLE
): Promise<Event> {
  const payload = {
    name: input.name ?? uniqueId('Event'),
    spotlight_slot_count: input.spotlight_slot_count ?? 2,
  };
  const res = await postAs('/events', payload, role);
  expectSuccess(res);
  return unwrap<Event>(res.body);
}

export async function getEvent(eventId: string, role: Role = DEFAULT_ROLE): Promise<Event> {
  const res = await getAs(`/events/${eventId}`, role);
  expectSuccess(res);
  return unwrap<Event>(res.body);
}

export async function updateEvent(
  eventId: string,
  updates: Partial<{ name: string; posture: EventPosture; spotlight_slot_count: number }>,
  version: number,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return patchWithVersion(`/events/${eventId}`, updates, version, role);
}

export async function runOps(eventId: string, role: Role = DEFAULT_ROLE): Promise<Response> {
  return postAs(`/events/${eventId}/run_ops`, {}, role);
}

export async function runOpsSuccess(eventId: string, role: Role = DEFAULT_ROLE): Promise<Event> {
  const res = await runOps(eventId, role);
  expectSuccess(res);
  return unwrap<Event>(res.body);
}

export interface CreatePackageInput {
  label?: string;
  price_cents?: number;
  slot_count?: number;
  included_benefits?: IncludedBenefit[];
}

export async function createPackage(
  eventId: string,
  input: CreatePackageInput = {},
  role: Role = DEFAULT_ROLE
): Promise<Package> {
  const payload = {
    label: input.label ?? uniqueId('Package'),
    price_cents: input.price_cents ?? 100000,
    slot_count: input.slot_count ?? 1,
    included_benefits: input.included_benefits ?? [],
  };
  const res = await postAs(`/events/${eventId}/packages`, payload, role);
  expectSuccess(res);
  return unwrap<Package>(res.body);
}

export async function getPackage(
  eventId: string,
  packageId: string,
  role: Role = DEFAULT_ROLE
): Promise<Package> {
  const res = await getAs(`/events/${eventId}/packages/${packageId}`, role);
  expectSuccess(res);
  return unwrap<Package>(res.body);
}

export async function transitionPackage(
  eventId: string,
  packageId: string,
  action: PackageAction,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return postAs(`/events/${eventId}/packages/${packageId}/transition`, { action }, role);
}

export async function retirePackage(
  eventId: string,
  packageId: string,
  role: Role = DEFAULT_ROLE
): Promise<void> {
  const res = await transitionPackage(eventId, packageId, 'RETIRE', role);
  expectSuccess(res);
}

export async function reactivatePackage(
  eventId: string,
  packageId: string,
  role: Role = DEFAULT_ROLE
): Promise<void> {
  const res = await transitionPackage(eventId, packageId, 'REACTIVATE', role);
  expectSuccess(res);
}

export interface CreateSponsorInput {
  display_name?: string;
  legal_name?: string;
  primary_contact_email?: string;
  status?: SponsorStatus;
}

export async function createSponsor(
  eventId: string,
  input: CreateSponsorInput = {},
  role: Role = DEFAULT_ROLE
): Promise<Sponsor> {
  const payload = {
    display_name: input.display_name ?? uniqueId('Sponsor'),
    legal_name: input.legal_name ?? `${input.display_name ?? uniqueId('Sponsor')} LLC`,
    primary_contact_email: input.primary_contact_email ?? `${uniqueId('contact')}@test.com`,
    status: input.status ?? 'PROSPECT',
  };
  const res = await postAs(`/events/${eventId}/sponsors`, payload, role);
  expectSuccess(res);
  return unwrap<Sponsor>(res.body);
}

export async function getSponsor(
  eventId: string,
  sponsorId: string,
  role: Role = DEFAULT_ROLE
): Promise<Sponsor> {
  const res = await getAs(`/events/${eventId}/sponsors/${sponsorId}`, role);
  expectSuccess(res);
  return unwrap<Sponsor>(res.body);
}

export async function updateSponsor(
  eventId: string,
  sponsorId: string,
  updates: Partial<{ display_name: string; legal_name: string; primary_contact_email: string; status: SponsorStatus }>,
  version: number,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return patchWithVersion(`/events/${eventId}/sponsors/${sponsorId}`, updates, version, role);
}

export async function updateSponsorStatus(
  eventId: string,
  sponsorId: string,
  status: SponsorStatus,
  version: number,
  role: Role = DEFAULT_ROLE
): Promise<Sponsor> {
  const res = await updateSponsor(eventId, sponsorId, { status }, version, role);
  expectSuccess(res);
  return unwrap<Sponsor>(res.body);
}

export interface CreateApplicationInput {
  sponsor_id: string;
  package_id: string;
  note?: string;
}

export async function createApplication(
  eventId: string,
  input: CreateApplicationInput,
  role: Role = DEFAULT_ROLE
): Promise<Application> {
  const payload = {
    sponsor_id: input.sponsor_id,
    package_id: input.package_id,
    note: input.note,
  };
  const res = await postAs(`/events/${eventId}/applications`, payload, role);
  expectSuccess(res);
  return unwrap<Application>(res.body);
}

export async function getApplication(
  eventId: string,
  applicationId: string,
  role: Role = DEFAULT_ROLE
): Promise<Application> {
  const res = await getAs(`/events/${eventId}/applications/${applicationId}`, role);
  expectSuccess(res);
  return unwrap<Application>(res.body);
}

export async function updateApplication(
  eventId: string,
  applicationId: string,
  updates: { note?: string },
  version: number,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return putWithVersion(`/events/${eventId}/applications/${applicationId}`, updates, version, role);
}

export async function transitionApplication(
  eventId: string,
  applicationId: string,
  action: ApplicationAction,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return postAs(`/events/${eventId}/applications/${applicationId}/transition`, { action }, role);
}

export async function submitApplication(
  eventId: string,
  applicationId: string,
  role: Role = DEFAULT_ROLE
): Promise<Application> {
  const res = await transitionApplication(eventId, applicationId, 'SUBMIT', role);
  expectSuccess(res);
  return unwrap<Application>(res.body);
}

export async function approveApplication(
  eventId: string,
  applicationId: string,
  role: Role = DEFAULT_ROLE
): Promise<{ application: Application; commitment: Commitment }> {
  const res = await transitionApplication(eventId, applicationId, 'APPROVE', role);
  expectSuccess(res);
  const data = unwrap(res.body);

  const app = await getApplication(eventId, applicationId, role);
  const commitment = await getCommitment(eventId, app.commitment_id!, role);

  return { application: app, commitment };
}

export async function rejectApplication(
  eventId: string,
  applicationId: string,
  role: Role = DEFAULT_ROLE
): Promise<Application> {
  const res = await transitionApplication(eventId, applicationId, 'REJECT', role);
  expectSuccess(res);
  return unwrap<Application>(res.body);
}

export async function withdrawApplication(
  eventId: string,
  applicationId: string,
  role: Role = DEFAULT_ROLE
): Promise<Application> {
  const res = await transitionApplication(eventId, applicationId, 'WITHDRAW', role);
  expectSuccess(res);
  return unwrap<Application>(res.body);
}

export async function getCommitment(
  eventId: string,
  commitmentId: string,
  role: Role = DEFAULT_ROLE
): Promise<Commitment> {
  const res = await getAs(`/events/${eventId}/commitments/${commitmentId}`, role);
  expectSuccess(res);
  const commitment = unwrap<Commitment>(res.body);

  commitment.benefits_left = normalizeBenefitsLeft(commitment.benefits_left);
  return commitment;
}

export async function transitionCommitment(
  eventId: string,
  commitmentId: string,
  action: CommitmentAction,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return postAs(`/events/${eventId}/commitments/${commitmentId}/transition`, { action }, role);
}

export async function countersignCommitment(
  eventId: string,
  commitmentId: string,
  role: Role = DEFAULT_ROLE
): Promise<Commitment> {
  const res = await transitionCommitment(eventId, commitmentId, 'COUNTERSIGN', role);
  expectSuccess(res);
  return unwrap<Commitment>(res.body);
}

export async function rescindCommitment(
  eventId: string,
  commitmentId: string,
  role: Role = DEFAULT_ROLE
): Promise<Commitment> {
  const res = await transitionCommitment(eventId, commitmentId, 'RESCIND', role);
  expectSuccess(res);
  return unwrap<Commitment>(res.body);
}

export interface CreateClaimInput {
  benefit_kind: BenefitKind;
  quantity: number;
}

export async function createClaim(
  eventId: string,
  commitmentId: string,
  input: CreateClaimInput,
  role: Role = DEFAULT_ROLE
): Promise<Claim> {
  const res = await postAs(`/events/${eventId}/commitments/${commitmentId}/claims`, input, role);
  expectSuccess(res);
  return unwrap<Claim>(res.body);
}

export async function transitionClaim(
  eventId: string,
  commitmentId: string,
  claimId: string,
  action: ClaimAction,
  role: Role = DEFAULT_ROLE
): Promise<Response> {
  return postAs(
    `/events/${eventId}/commitments/${commitmentId}/claims/${claimId}/transition`,
    { action },
    role
  );
}

export async function finalizeClaim(
  eventId: string,
  commitmentId: string,
  claimId: string,
  role: Role = DEFAULT_ROLE
): Promise<Claim> {
  const res = await transitionClaim(eventId, commitmentId, claimId, 'FINALIZE', role);
  expectSuccess(res);
  return unwrap<Claim>(res.body);
}

export async function voidClaim(
  eventId: string,
  commitmentId: string,
  claimId: string,
  role: Role = DEFAULT_ROLE
): Promise<Claim> {
  const res = await transitionClaim(eventId, commitmentId, claimId, 'VOID', role);
  expectSuccess(res);
  return unwrap<Claim>(res.body);
}

export async function createEventDraft(
  name?: string,
  spotlightSlotCount: number = 2
): Promise<Event> {
  return createEvent({ name: name ?? uniqueId('Event'), spotlight_slot_count: spotlightSlotCount });
}

export async function createEventOpen(
  name?: string,
  spotlightSlotCount: number = 2
): Promise<Event> {
  const event = await createEventDraft(name, spotlightSlotCount);
  const res = await updateEvent(event.id, { posture: 'OPEN' }, event.version);
  expectSuccess(res);
  return getEvent(event.id);
}

export async function createGoldSilverPackages(eventId: string): Promise<{ gold: Package; silver: Package }> {
  const gold = await createPackage(eventId, {
    label: 'GOLD',
    price_cents: 500000,
    slot_count: 1,
    included_benefits: [
      { benefit_kind: 'LEAD_SCANS', quantity: 100 },
      { benefit_kind: 'STAGE_MINUTES', quantity: 30 },
      { benefit_kind: 'SPOTLIGHT', quantity: 1 },
    ],
  });

  const silver = await createPackage(eventId, {
    label: 'SILVER',
    price_cents: 250000,
    slot_count: 2,
    included_benefits: [
      { benefit_kind: 'LEAD_SCANS', quantity: 50 },
      { benefit_kind: 'STAGE_MINUTES', quantity: 15 },
    ],
  });

  return { gold, silver };
}

export async function createDraftApplicationVettedGold(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
}> {
  const event = await createEventOpen();
  const { gold, silver } = await createGoldSilverPackages(event.id);
  const sponsor = await createSponsor(event.id, {
    display_name: 'BetaCorp',
    legal_name: 'BetaCorp Inc',
    primary_contact_email: 'devrel@beta.test',
    status: 'VETTED',
  });
  const application = await createApplication(event.id, {
    sponsor_id: sponsor.id,
    package_id: gold.id,
    note: 'we want gold',
  });

  return { event, gold, silver, sponsor, application };
}

export async function createSubmittedHeldApplicationVettedGold(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
}> {
  const fixture = await createDraftApplicationVettedGold();
  const application = await submitApplication(fixture.event.id, fixture.application.id);
  return { ...fixture, application };
}

export async function createWaitlistTwoAppsGold(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor1: Sponsor;
  sponsor2: Sponsor;
  application1: Application;
  application2: Application;
}> {
  const event = await createEventOpen();
  const { gold, silver } = await createGoldSilverPackages(event.id);

  const sponsor1 = await createSponsor(event.id, {
    display_name: 'S1',
    legal_name: 'S1 LLC',
    primary_contact_email: 'a@s1.test',
    status: 'VETTED',
  });

  const sponsor2 = await createSponsor(event.id, {
    display_name: 'S2',
    legal_name: 'S2 LLC',
    primary_contact_email: 'a@s2.test',
    status: 'VETTED',
  });

  const app1 = await createApplication(event.id, { sponsor_id: sponsor1.id, package_id: gold.id });
  const application1 = await submitApplication(event.id, app1.id);

  const app2 = await createApplication(event.id, { sponsor_id: sponsor2.id, package_id: gold.id });
  const application2 = await submitApplication(event.id, app2.id);

  return { event, gold, silver, sponsor1, sponsor2, application1, application2 };
}

export async function createActiveCommitmentVettedGold(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
  commitment: Commitment;
}> {
  const fixture = await createSubmittedHeldApplicationVettedGold();
  const { application, commitment: approvedCommitment } = await approveApplication(fixture.event.id, fixture.application.id);

  let commitment = approvedCommitment;
  if (commitment.status !== 'ACTIVE') {
    commitment = await countersignCommitment(fixture.event.id, commitment.id);
  }

  return { ...fixture, application, commitment };
}

export async function createPendingCommitmentProspectGold(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
  commitment: Commitment;
}> {
  const event = await createEventOpen();
  const { gold, silver } = await createGoldSilverPackages(event.id);

  const sponsor = await createSponsor(event.id, {
    display_name: 'Prospect',
    legal_name: 'Prospect LLC',
    primary_contact_email: 'p@p.test',
    status: 'PROSPECT',
  });

  const app = await createApplication(event.id, { sponsor_id: sponsor.id, package_id: gold.id });
  const submittedApp = await submitApplication(event.id, app.id);
  const { application, commitment } = await approveApplication(event.id, submittedApp.id);

  return { event, gold, silver, sponsor, application, commitment };
}

export async function createSuspendedCommitmentWatchlistGold(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
  commitment: Commitment;
}> {
  const event = await createEventOpen();
  const { gold, silver } = await createGoldSilverPackages(event.id);

  const sponsor = await createSponsor(event.id, {
    display_name: 'WL',
    legal_name: 'WL LLC',
    primary_contact_email: 'wl@wl.test',
    status: 'VETTED',
  });

  const app = await createApplication(event.id, { sponsor_id: sponsor.id, package_id: gold.id });
  const submittedApp = await submitApplication(event.id, app.id);
  let { application, commitment } = await approveApplication(event.id, submittedApp.id);

  if (commitment.status !== 'ACTIVE') {
    commitment = await countersignCommitment(event.id, commitment.id);
  }

  const updatedSponsor = await getSponsor(event.id, sponsor.id);
  await updateSponsorStatus(event.id, sponsor.id, 'WATCHLIST', updatedSponsor.version);

  commitment = await getCommitment(event.id, commitment.id);

  const finalSponsor = await getSponsor(event.id, sponsor.id);

  return { event, gold, silver, sponsor: finalSponsor, application, commitment };
}

export async function createActiveWithFinalizedLeads(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
  commitment: Commitment;
  claim: Claim;
}> {
  const fixture = await createActiveCommitmentVettedGold();
  const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
    benefit_kind: 'LEAD_SCANS',
    quantity: 30,
  });
  await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);
  const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
  return { ...fixture, commitment, claim };
}

export async function createActiveWithFinalizedSpotlight(): Promise<{
  event: Event;
  gold: Package;
  silver: Package;
  sponsor: Sponsor;
  application: Application;
  commitment: Commitment;
  claim: Claim;
}> {
  const fixture = await createActiveCommitmentVettedGold();
  const claim = await createClaim(fixture.event.id, fixture.commitment.id, {
    benefit_kind: 'SPOTLIGHT',
    quantity: 1,
  });
  await finalizeClaim(fixture.event.id, fixture.commitment.id, claim.id);
  const commitment = await getCommitment(fixture.event.id, fixture.commitment.id);
  return { ...fixture, commitment, claim };
}

export async function createTwoFinalizedSpotlightsEventFull(): Promise<{
  event: Event;
  gold: Package;
  sponsorA: Sponsor;
  sponsorB: Sponsor;
  commitmentA: Commitment;
  commitmentB: Commitment;
  claimA: Claim;
  claimB: Claim;
}> {
  const event = await createEventOpen(uniqueId('FullSpotlight'), 2);

  const gold = await createPackage(event.id, {
    label: 'GOLD',
    price_cents: 500000,
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

  const appA = await createApplication(event.id, { sponsor_id: sponsorA.id, package_id: gold.id });
  await submitApplication(event.id, appA.id);
  let { commitment: commitmentA } = await approveApplication(event.id, appA.id);

  if (commitmentA.status !== 'ACTIVE') {
    commitmentA = await countersignCommitment(event.id, commitmentA.id);
  }

  const appB = await createApplication(event.id, { sponsor_id: sponsorB.id, package_id: gold.id });
  await submitApplication(event.id, appB.id);
  let { commitment: commitmentB } = await approveApplication(event.id, appB.id);

  if (commitmentB.status !== 'ACTIVE') {
    commitmentB = await countersignCommitment(event.id, commitmentB.id);
  }

  const claimA = await createClaim(event.id, commitmentA.id, { benefit_kind: 'SPOTLIGHT', quantity: 1 });
  await finalizeClaim(event.id, commitmentA.id, claimA.id);

  const claimB = await createClaim(event.id, commitmentB.id, { benefit_kind: 'SPOTLIGHT', quantity: 1 });
  await finalizeClaim(event.id, commitmentB.id, claimB.id);

  return {
    event: await getEvent(event.id),
    gold,
    sponsorA,
    sponsorB,
    commitmentA: await getCommitment(event.id, commitmentA.id),
    commitmentB: await getCommitment(event.id, commitmentB.id),
    claimA,
    claimB,
  };
}
