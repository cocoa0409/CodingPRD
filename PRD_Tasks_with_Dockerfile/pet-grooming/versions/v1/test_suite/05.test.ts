import { AxiosResponse } from 'axios';
import {
  apiClient,
  buildUserHeaders,
  validateErrorEnvelope,
  getSuccessData,
  createAndActivateGroomingDay,
  createSessionBlock,
  createGroomingJob,
  createGroomerStation,
  createJobAssignment,
  confirmJobAssignment, fillSessionBlockWithJobs, GroomingDay,
  SessionBlock,
  GroomingJob, JobAssignment,
  SessionBlockStatus,
  ApiResponse,
  UserRole,
  ApiErrorId,
  JobAssignmentStatus,
  GroomingJobStatus,
  GroomingDayStatus,
  RequiredAllergenType
} from '../../../test-helpers';
import { createUnixTimestamp, addMinutes, addHours, generatePetId } from '../../../test-helpers/utils';

describe('Phase 4: Edge Cases', () => {
  const clinicManagerHeaders = buildUserHeaders('clinic-mgr-1', UserRole.ClinicManager);
  const groomerTechHeaders = buildUserHeaders('groomer-1', UserRole.GroomingTechnician);
  const billingAdminHeaders = buildUserHeaders('billing-1', UserRole.BillingAdmin);

  const createAndActivateDay = async (payload?: { total_supply_budget?: number; schedule_name?: string }) => {
    const day = await createAndActivateGroomingDay(
      payload?.schedule_name || 'Full Service Day',
      payload?.total_supply_budget || 50000.0
    );
    return day;
  };

  it('should increment allergy score for peak/override and restore it on termination', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 50000.0 });
    const block = await createSessionBlock(day.id, 'Morning Block', 0, 8);

    const station = await createGroomerStation(
      day.id,
      'Standard Station',
      'Standard',
      50.0
    );

    const job1 = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(1),
      'Extended Grooming',
      0,
      6000,
    );
    const assignment1 = await createJobAssignment(day.id, job1.id, station.id);
    await confirmJobAssignment(day.id, assignment1.id);

    const dayAfterAssignment1 = await apiClient
      .getGroomingDay(day.id, clinicManagerHeaders)
      .then((r: AxiosResponse<ApiResponse<GroomingDay>>) => getSuccessData<GroomingDay>(r));
    expect(dayAfterAssignment1.allergy_exposure_score).toBe(0);

    const jobs = await fillSessionBlockWithJobs(day.id, block.id, 4, 100.5, { jobDurationMinutes: 60 });
    for (const job of jobs) {
      const assignment = await createJobAssignment(day.id, job.id, station.id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const peakJob = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(200),
      'Peak Grooming',
      105.6,
      60
    );

    const peakAssignment = await createJobAssignment(day.id, peakJob.id, station.id);

    const dayAfterPeakAssignment = await apiClient
      .getGroomingDay(day.id, clinicManagerHeaders)
      .then((r: AxiosResponse<ApiResponse<GroomingDay>>) => getSuccessData<GroomingDay>(r));
    expect(dayAfterPeakAssignment.allergy_exposure_score).toBe(10);

    await apiClient.terminateJobAssignment(day.id, peakAssignment.id, clinicManagerHeaders);

    const dayAfterTermination = await apiClient
      .getGroomingDay(day.id, clinicManagerHeaders)
      .then((r: AxiosResponse<ApiResponse<GroomingDay>>) => getSuccessData<GroomingDay>(r));
    expect(dayAfterTermination.allergy_exposure_score).toBe(0);
  });

  it('should prevent allergy score from going below zero when decrementing', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 50000.0 });
    const block = await createSessionBlock(day.id, 'Morning Block', 0, 8);
    const station1 = await createGroomerStation(
      day.id,
      'Station 1',
      'Standard',
      1.0
    );
    const station2 = await createGroomerStation(
      day.id,
      'Station 2',
      'Standard',
      1.0
    );

    for (let i = 0; i < 5; i++) {
      const job = await createGroomingJob(
        day.id,
        block.id,
        generatePetId(i + 1),
        `Job ${i + 1}`,
        i,
        30
      );
      const assignment = await createJobAssignment(day.id, job.id, i % 2 === 0 ? station1.id : station2.id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const peakJob = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(100),
      'Peak Job',
      6,
      30
    );
    const peakAssignment = await createJobAssignment(day.id, peakJob.id, station1.id, { overrideAllergyCheck: true });

    const dayWithPenalty = await apiClient
      .getGroomingDay(day.id, clinicManagerHeaders)
      .then((r: AxiosResponse<ApiResponse<GroomingDay>>) => getSuccessData<GroomingDay>(r));
    expect(dayWithPenalty.allergy_exposure_score).toBe(10);

    await apiClient.terminateJobAssignment(day.id, peakAssignment.id, clinicManagerHeaders);

    const dayAfterFinal = await apiClient
      .getGroomingDay(day.id, clinicManagerHeaders)
      .then((r: AxiosResponse<ApiResponse<GroomingDay>>) => getSuccessData<GroomingDay>(r));
    expect(dayAfterFinal.allergy_exposure_score).toBeGreaterThanOrEqual(0);
  });

  it('should allow reading session blocks from a CLOSED day', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 1000.0 });
    const block = await createSessionBlock(day.id, 'Test Block', 0, 8);

    await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);
    await apiClient.generateInvoiceReport(day.id, billingAdminHeaders);

    const closedDay = await apiClient
      .getGroomingDay(day.id, clinicManagerHeaders)
      .then((r: AxiosResponse<ApiResponse<GroomingDay>>) => getSuccessData<GroomingDay>(r));
    expect(closedDay.status).toBe('CLOSED');

    const blocksRes = await apiClient.getSessionBlocks(day.id, clinicManagerHeaders);
    expect(blocksRes.status).toBe(200);
    const blocks = getSuccessData<SessionBlock[]>(blocksRes);
    expect(blocks.length).toBe(1);
    expect(blocks[0].id).toBe(block.id);
  });

  it('should allow reading job assignments from a PLANNING day', async () => {
    const dayRes = await apiClient.createGroomingDay(
      { schedule_name: 'Planning Day', total_supply_budget: 5000.0 },
      clinicManagerHeaders
    );
    const day = getSuccessData<GroomingDay>(dayRes);
    expect(day.status).toBe('PLANNING');

    const assignmentsRes = await apiClient.getJobAssignments(day.id, groomerTechHeaders);
    expect(assignmentsRes.status).toBe(200);
    const assignments = getSuccessData<JobAssignment[]>(assignmentsRes);
    expect(assignments).toEqual([]);
  });

  it('should reject assignment when station is missing the required allergy capability', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 2000.0 });
    const block = await createSessionBlock(day.id, 'Test Block', 0, 8);
    const station = await createGroomerStation(day.id, 'Basic Station', 'Standard', 25.0);

    const allergyJob = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(1),
      'Allergy Grooming',
      0,
      60,
      { requiredAllergenType: RequiredAllergenType.NUT_ALLERGY }
    );

    const assignmentRes = await apiClient.createJobAssignment(
      day.id,
      { job_id: allergyJob.id, station_id: station.id },
      groomerTechHeaders
    );

    validateErrorEnvelope(assignmentRes, {
      expectedErrorId: ApiErrorId.ERR_CAPABILITY_MISMATCH,
    });
  });

  it('should enforce groomer break period within the same day on the same station', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 2000.0 });
    const block = await createSessionBlock(day.id, 'Test Block', 0, 8);
    const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 25.0);

    const baseTime = createUnixTimestamp(0);

    const job1 = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(1),
      'First Grooming',
      0,
      60
    );
    const assignment1 = await createJobAssignment(day.id, job1.id, station.id);
    await confirmJobAssignment(day.id, assignment1.id);

    const job2 = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(2),
      'Second Grooming',
      1.2,
      60
    );

    const assignment2Res = await apiClient.createJobAssignment(
      day.id,
      { job_id: job2.id, station_id: station.id },
      groomerTechHeaders
    );

    validateErrorEnvelope(assignment2Res, {
      expectedErrorId: ApiErrorId.ERR_BREAK_PERIOD_VIOLATION,
    });

    const job3 = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(3),
      'Third Grooming',
      1.5,
      60
    );

    const assignment3Res = await apiClient.createJobAssignment(
      day.id,
      { job_id: job3.id, station_id: station.id },
      groomerTechHeaders
    );

    expect(assignment3Res.status).toBe(201);
  });

  it('should apply peak session surcharge based on assignment order within session block', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 50000.0 });
    const block = await createSessionBlock(day.id, 'Peak Test Block', 0, 12);
    const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 100.0);

    const regularJobs = await fillSessionBlockWithJobs(day.id, block.id, 4, 0, {
      jobDurationMinutes: 60,
      jobType: 'Regular Grooming'
    });

    const regularAssignments: JobAssignment[] = [];
    for (const job of regularJobs) {
      const assignment = await createJobAssignment(day.id, job.id, station.id);
      const confirmed = await confirmJobAssignment(day.id, assignment.id);
      regularAssignments.push(confirmed);
    }

    const fifthJob = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(100),
      'Fifth Grooming (Not Peak)',
      5.1,
      60
    );
    const fifthAssignment = await createJobAssignment(day.id, fifthJob.id, station.id);
    const confirmedFifthAssignment = await confirmJobAssignment(day.id, fifthAssignment.id);

    const peakJob = await createGroomingJob(
      day.id,
      block.id,
      generatePetId(101),
      'Peak Grooming',
      6.4,
      60
    );
    const peakAssignment = await createJobAssignment(day.id, peakJob.id, station.id);
    const confirmedPeakAssignment = await confirmJobAssignment(day.id, peakAssignment.id);

    await apiClient.initiateInvoicing(day.id, clinicManagerHeaders);
    await apiClient.generateInvoiceReport(day.id, billingAdminHeaders);

    const finalRegularAssignment = await apiClient.getJobAssignment(day.id, regularAssignments[0].id, groomerTechHeaders)
      .then(r => getSuccessData<JobAssignment>(r));
    expect(finalRegularAssignment.final_supply_cost).toBeCloseTo(100.0);

    const finalFifthAssignment = await apiClient.getJobAssignment(day.id, confirmedFifthAssignment.id, groomerTechHeaders)
      .then(r => getSuccessData<JobAssignment>(r));
    expect(finalFifthAssignment.final_supply_cost).toBeCloseTo(100.0);

    const finalPeakAssignment = await apiClient.getJobAssignment(day.id, confirmedPeakAssignment.id, groomerTechHeaders)
      .then(r => getSuccessData<JobAssignment>(r));
    expect(finalPeakAssignment.final_supply_cost).toBeCloseTo(150.0);
  });

  it('should downgrade READY block when an assignment is terminated and prevent re-marking', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 10000.0 });
    const block = await createSessionBlock(day.id, 'Ready Test Block', 0, 8);
    const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 25.0);

    const job = await createGroomingJob(day.id, block.id, generatePetId(1), 'Test Grooming', 0, 60);
    const assignment = await createJobAssignment(day.id, job.id, station.id);
    await confirmJobAssignment(day.id, assignment.id);

    const readyRes = await apiClient.updateSessionBlockStatus(
      day.id,
      block.id,
      { status: SessionBlockStatus.READY_FOR_GROOMING },
      clinicManagerHeaders
    );
    const readyBlock = getSuccessData<SessionBlock>(readyRes);
    expect(readyBlock.status).toBe(SessionBlockStatus.READY_FOR_GROOMING);

    await apiClient.terminateJobAssignment(day.id, assignment.id, clinicManagerHeaders);

    const blockCheckRes = await apiClient.getSessionBlock(day.id, block.id, groomerTechHeaders);
    const downgradedBlock = getSuccessData<SessionBlock>(blockCheckRes);
    expect(downgradedBlock.status).toBe(SessionBlockStatus.PLANNING);

    const jobCheckRes = await apiClient.getGroomingJob(day.id, block.id, job.id, groomerTechHeaders);
    const reopenedJob = getSuccessData<GroomingJob>(jobCheckRes);
    expect(reopenedJob.status).toBe(GroomingJobStatus.PENDING);

    const retryReadyRes = await apiClient.updateSessionBlockStatus(
      day.id,
      block.id,
      { status: SessionBlockStatus.READY_FOR_GROOMING },
      clinicManagerHeaders
    );
    validateErrorEnvelope(retryReadyRes, { expectedErrorId: ApiErrorId.ERR_JOBS_NOT_CONFIRMED });
  });

  it('should cascade cancellation from block and revert ledger entries', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 20000.0 });
    const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 50.0);

    const setupBlock = await createSessionBlock(day.id, 'Baseline Block', 0, 8);
    const baselineJobs = await fillSessionBlockWithJobs(day.id, setupBlock.id, 6, 0, { jobDurationMinutes: 60 });
    for (const job of baselineJobs) {
      const assignment = await createJobAssignment(day.id, job.id, station.id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const baselineState = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    const baseBudget = baselineState.supply_stock_balance;
    const baseAllergyScore = baselineState.allergy_exposure_score;
    expect(baseAllergyScore).toBe(10);

    const blockToCancel = await createSessionBlock(day.id, 'Block to Cancel', 24, 8);

    const regularJob = await createGroomingJob(
      day.id,
      blockToCancel.id,
      generatePetId(100),
      'Regular Grooming',
      24,
      60
    );
    const regularAssignment = await createJobAssignment(day.id, regularJob.id, station.id);

    for (let i = 0; i < 9; i++) {
      const job = await createGroomingJob(
        day.id,
        blockToCancel.id,
        generatePetId(200 + i),
        'Peak Grooming',
        25.5 + (i * 1.27),
        60
      );

      const useOverride = i >= 7;
      const assignment = await createJobAssignment(
        day.id,
        job.id,
        station.id,
        { overrideAllergyCheck: useOverride }
      );
    }

    const lowAllergyState = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(lowAllergyState.allergy_exposure_score).toBeGreaterThan(baseAllergyScore);

    const overrideJob = await createGroomingJob(
      day.id,
      blockToCancel.id,
      generatePetId(300),
      'Override Grooming',
      25.5 + (9 * 1.27) + 0.3,
      60
    );
    const overrideAssignment = await createJobAssignment(
      day.id,
      overrideJob.id,
      station.id,
      { overrideAllergyCheck: true }
    );

    const intermediateState = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(intermediateState.supply_stock_balance).toBeLessThan(baseBudget);
    expect(intermediateState.allergy_exposure_score).toBeGreaterThan(lowAllergyState.allergy_exposure_score);

    await apiClient.updateSessionBlockStatus(
      day.id,
      blockToCancel.id,
      { status: SessionBlockStatus.CANCELLED },
      clinicManagerHeaders
    );

    const finalRegularAssignment = await apiClient.getJobAssignment(day.id, regularAssignment.id, groomerTechHeaders)
      .then(r => getSuccessData<JobAssignment>(r));
    expect(finalRegularAssignment.status).toBe(JobAssignmentStatus.TERMINATED);

    const finalOverrideAssignment = await apiClient.getJobAssignment(day.id, overrideAssignment.id, groomerTechHeaders)
      .then(r => getSuccessData<JobAssignment>(r));
    expect(finalOverrideAssignment.status).toBe(JobAssignmentStatus.TERMINATED);

    const finalState = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(finalState.supply_stock_balance).toBeCloseTo(baseBudget);
    expect(finalState.allergy_exposure_score).toBe(baseAllergyScore);
  });

  it('should have the day allergy score reflect ledger changes immediately', async () => {
    const day = await createAndActivateDay({ total_supply_budget: 50000.0 });
    const station = await createGroomerStation(day.id, 'Test Station', 'Standard', 10.0);
    const block = await createSessionBlock(day.id, 'Immediate Update Test', 0, 12);

    const baseJobs = await fillSessionBlockWithJobs(day.id, block.id, 6, 0, { jobDurationMinutes: 60 });
    for (const job of baseJobs) {
      const assignment = await createJobAssignment(day.id, job.id, station.id);
      await confirmJobAssignment(day.id, assignment.id);
    }

    const state0 = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(state0.allergy_exposure_score).toBe(10);

    const peakJob = await createGroomingJob(day.id, block.id, generatePetId(100), 'Peak Grooming', 8, 60);
    const peakAssignment = await createJobAssignment(day.id, peakJob.id, station.id);
    const state1 = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(state1.allergy_exposure_score).toBe(20);

    await apiClient.terminateJobAssignment(day.id, peakAssignment.id, clinicManagerHeaders);
    const state2 = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(state2.allergy_exposure_score).toBe(10);

    for (let i = 0; i < 3; i++) {
      const job = await createGroomingJob(day.id, block.id, generatePetId(200 + i), 'Multi Peak', 9.5 + (i * 1.3), 60);
      await createJobAssignment(day.id, job.id, station.id);
    }
    const state3 = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(state3.allergy_exposure_score).toBe(40);

    const atThresholdState = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(atThresholdState.allergy_exposure_score).toBe(40);

    const overrideJob = await createGroomingJob(day.id, block.id, generatePetId(400), 'Explicit Override', 24, 60);
    const overrideAssignment = await createJobAssignment(day.id, overrideJob.id, station.id, { overrideAllergyCheck: true });
    const state4 = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(state4.allergy_exposure_score).toBe(75);

    await apiClient.terminateJobAssignment(day.id, overrideAssignment.id, clinicManagerHeaders);
    const state5 = await apiClient.getGroomingDay(day.id, clinicManagerHeaders)
      .then(r => getSuccessData<GroomingDay>(r));
    expect(state5.allergy_exposure_score).toBe(40);
  });
});
