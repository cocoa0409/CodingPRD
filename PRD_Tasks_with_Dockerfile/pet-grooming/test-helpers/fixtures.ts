import { apiClient } from './api-client';
import { getSuccessData } from './validators';
import { buildUserHeaders, createUnixTimestamp, addHours, formatDate, generatePetId } from './utils';
import {
  UserRole,
  GroomingDay,
  SessionBlock,
  GroomingJob,
  GroomerStation,
  JobAssignment,
  RequiredAllergenType,
  SpecialCapabilityName,
} from './types';

export async function createAndActivateGroomingDay(
  scheduleName: string,
  totalBudget: number,
  userId: string = 'manager-001',
): Promise<GroomingDay> {
  const headers = buildUserHeaders(userId, UserRole.ClinicManager);

  const createResponse = await apiClient.createGroomingDay(
    { schedule_name: scheduleName, total_supply_budget: totalBudget },
    headers
  );
  const groomingDay = getSuccessData<GroomingDay>(createResponse);

  const activateResponse = await apiClient.activateGroomingDay(groomingDay.id, headers);
  return getSuccessData<GroomingDay>(activateResponse);
}

export async function createSessionBlock(
  dayId: string,
  name: string,
  hoursFromNow: number,
  durationHours: number,
  userId: string = 'tech-001',
): Promise<SessionBlock> {
  const headers = buildUserHeaders(userId, UserRole.GroomingTechnician);
  const startTime = createUnixTimestamp(hoursFromNow);
  const endTime = addHours(startTime, durationHours);

  const response = await apiClient.createSessionBlock(
    dayId,
    { name, start_time: startTime, end_time: endTime },
    headers
  );

  return getSuccessData<SessionBlock>(response);
}

export async function createGroomingJob(
  dayId: string,
  blockId: string,
  petId: string,
  jobType: string,
  startHoursFromNow: number,
  durationMinutes: number,
  options: {
    requiredAllergenType?: RequiredAllergenType;
    cannotBeGroomedWithPetIds?: string[];
    userId?: string;
  } = {},
): Promise<GroomingJob> {
  const headers = buildUserHeaders(
    options.userId || 'tech-001',
    UserRole.GroomingTechnician
  );

  const startTime = createUnixTimestamp(startHoursFromNow);
  const endTime = startTime + (durationMinutes * 60);

  const payload = {
    pet_id: petId,
    job_type: jobType,
    start_time: startTime,
    end_time: endTime,
    required_allergen_type: options.requiredAllergenType,
    cannot_be_groomed_with_pet_ids: options.cannotBeGroomedWithPetIds,
  };

  const response = await apiClient.createGroomingJob(dayId, blockId, payload, headers);
  return getSuccessData<GroomingJob>(response);
}

export async function createGroomerStation(
  dayId: string,
  stationName: string,
  stationType: string,
  costPerHour: number,
  capabilities: SpecialCapabilityName[] = [],
  userId: string = 'tech-001',
): Promise<GroomerStation> {
  const headers = buildUserHeaders(userId, UserRole.GroomingTechnician);

  const createResponse = await apiClient.createGroomerStation(
    dayId,
    {
      station_name: stationName,
      station_type: stationType,
      supply_cost_per_hour: costPerHour
    },
    headers
  );
  const station = getSuccessData<GroomerStation>(createResponse);

  for (const capability of capabilities) {
    await apiClient.addSpecialCapability(
      dayId,
      station.id,
      { name: capability, enabled_date: formatDate(new Date()) },
      headers
    );
  }

  const getResponse = await apiClient.getGroomerStation(dayId, station.id, headers);
  return getSuccessData<GroomerStation>(getResponse);
}

export async function createJobAssignment(
  dayId: string,
  jobId: string,
  stationId: string,
  options: {
    overrideAllergyCheck?: boolean;
    userId?: string;
  } = {},
): Promise<JobAssignment> {
  const headers = buildUserHeaders(
    options.userId || 'tech-001',
    UserRole.GroomingTechnician
  );

  const payload = {
    job_id: jobId,
    station_id: stationId,
    override_allergy_check: options.overrideAllergyCheck,
  };

  const response = await apiClient.createJobAssignment(dayId, payload, headers);
  return getSuccessData<JobAssignment>(response);
}

export async function confirmJobAssignment(
  dayId: string,
  assignmentId: string,
  userId: string = 'manager-001',
): Promise<JobAssignment> {
  const headers = buildUserHeaders(userId, UserRole.ClinicManager);
  const response = await apiClient.confirmJobAssignment(dayId, assignmentId, headers);
  return getSuccessData<JobAssignment>(response);
}

export async function fillSessionBlockWithJobs(
  dayId: string,
  blockId: string,
  jobCount: number,
  startHoursFromNow: number,
  options: {
    jobDurationMinutes?: number;
    jobType?: string;
    userId?: string;
  } = {},
): Promise<GroomingJob[]> {
  const jobs: GroomingJob[] = [];
  const jobDuration = options.jobDurationMinutes || 30;
  const breakMinutes = 16;

  for (let i = 0; i < jobCount; i++) {

    const jobStartHours = startHoursFromNow + (i * (jobDuration + breakMinutes) / 60);
    const job = await createGroomingJob(
      dayId,
      blockId,
      generatePetId(i + 1),
      options.jobType || 'Basic Grooming',
      jobStartHours,
      jobDuration,
      { userId: options.userId }
    );
    jobs.push(job);
  }

  return jobs;
}

export async function createPeakSessionAssignments(
  dayId: string,
  blockId: string,
  stationId: string,
  assignmentCount: number,
  startHoursFromNow: number,
): Promise<JobAssignment[]> {
  const assignments: JobAssignment[] = [];

  for (let i = 0; i < assignmentCount; i++) {
    const job = await createGroomingJob(
      dayId,
      blockId,
      generatePetId(i + 100),
      'Peak Grooming',
      startHoursFromNow + i,
      45
    );

    const assignment = await createJobAssignment(dayId, job.id, stationId);
    const confirmed = await confirmJobAssignment(dayId, assignment.id);
    assignments.push(confirmed);
  }

  return assignments;
}

export async function markSessionBlockReady(
  dayId: string,
  blockId: string,
  userId: string = 'manager-001',
): Promise<SessionBlock> {
  const headers = buildUserHeaders(userId, UserRole.ClinicManager);
  const response = await apiClient.updateSessionBlockStatus(
    dayId,
    blockId,
    { status: 'READY_FOR_GROOMING' as any },
    headers
  );
  return getSuccessData<SessionBlock>(response);
}
